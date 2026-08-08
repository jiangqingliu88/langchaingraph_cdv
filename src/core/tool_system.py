"""
Tool System — 借鉴 Claude Code 的 Tool Schema / Permission / ProjectMemory

三层:
  1. Tool + ToolRegistry — JSON Schema 标准化 + 参数验证 + LLM 输出纠错
  2. Sandbox — risk_level 权限控制 (safe/write/danger)
  3. ProjectMemory — 跨 run 持久记忆 (valiflow.md 概念)

用法:
  tool = Tool("run_vcs", desc="Compile and run VCS", input_schema={...}, risk_level="safe")
  registry = ToolRegistry()
  registry.register(tool)
  result = registry.invoke("run_vcs", {"tb": "tb_top.sv"})  # validates args vs schema
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional


# ═══════════════════════════════════════════════════════════
# Risk Level
# ═══════════════════════════════════════════════════════════

RiskLevel = Literal["safe", "write", "danger"]

RISK_RULES = {
    "safe":   {"approve": "auto",    "desc": "只读/无副作用 — 自动通过"},
    "write":  {"approve": "console", "desc": "写磁盘/改配置 — 终端确认"},
    "danger": {"approve": "block",   "desc": "删除/提权/杀进程 — 直接拦截"},
}


# ═══════════════════════════════════════════════════════════
# Tool + ToolRegistry
# ═══════════════════════════════════════════════════════════

@dataclass
class Tool:
    """标准化 Tool 定义 — LLM 按 input_schema 生成 args，框架自动 validate"""
    name: str
    description: str                          # 给 LLM 看的，决定何时调用
    input_schema: Dict[str, Any] = field(default_factory=dict)  # JSON Schema
    risk_level: RiskLevel = "safe"
    handler: Optional[Callable] = None        # 实际执行函数 fn(args) -> dict

    def validate_args(self, args: dict) -> tuple[bool, str]:
        """按 input_schema 验证 args。返回 (pass, error_msg)。"""
        if not self.input_schema:
            return True, ""
        props = self.input_schema.get("properties", {})
        required = self.input_schema.get("required", [])
        # 必填字段检查
        for r in required:
            if r not in args:
                return False, f"Missing required field: '{r}'"
        # 类型检查
        for key, val in args.items():
            if key not in props:
                continue
            expected = props[key]
            expected_type = expected.get("type", "string")
            if expected_type == "string" and not isinstance(val, str):
                return False, f"Field '{key}' expected string, got {type(val).__name__}"
            if expected_type == "integer" and not isinstance(val, int):
                return False, f"Field '{key}' expected int, got {type(val).__name__}"
            if expected_type == "number" and not isinstance(val, (int, float)):
                return False, f"Field '{key}' expected number, got {type(val).__name__}"
            # enum 检查
            if "enum" in expected and val not in expected["enum"]:
                return False, f"Field '{key}'={val} not in {expected['enum']}"
        return True, ""

    def to_llm_description(self) -> dict:
        """转为 LLM function-calling 格式 (OpenAI tool spec)"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolRegistry:
    """Tool 注册中心 — 注册/验证/调用"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_many(self, tools: List[Tool]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_llm_specs(self) -> List[dict]:
        """返回所有 Tool 的 LLM 规格（给 Agent prompt 用）"""
        return [t.to_llm_description() for t in self._tools.values()]

    def invoke(self, name: str, args: dict,
               sandbox: "Sandbox" = None) -> Dict[str, Any]:
        """调用 Tool: validate → permission check → execute。返回 {success, result, error}。"""
        tool = self._tools.get(name)
        if not tool:
            return {"success": False, "error": f"Tool '{name}' not found"}
        # Schema 验证
        ok, err = tool.validate_args(args)
        if not ok:
            return {"success": False, "error": f"Schema validation failed: {err}"}
        # 权限检查
        if sandbox:
            ok, err = sandbox.check(tool, args)
            if not ok:
                return {"success": False, "error": f"Sandbox blocked: {err}"}
        # 执行
        if not tool.handler:
            return {"success": False, "error": f"Tool '{name}' has no handler"}
        try:
            result = tool.handler(args)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)[:500]}


# ═══════════════════════════════════════════════════════════
# Sandbox — 权限控制
# ═══════════════════════════════════════════════════════════

class Sandbox:
    """风险控制 — 按 Tool.risk_level 分级审批"""

    def __init__(self, allowed_root: str = ".", console_approve: bool = True):
        self.allowed_root = Path(allowed_root).resolve()
        self.console_approve = console_approve
        self.blocked_count = 0
        self.allowed_count = 0

    def check(self, tool: Tool, args: dict) -> tuple[bool, str]:
        """检查工具是否允许执行。返回 (pass, reason)。"""
        rule = RISK_RULES.get(tool.risk_level, RISK_RULES["safe"])
        if rule["approve"] == "auto":
            self.allowed_count += 1
            return True, "auto-approved"
        if rule["approve"] == "block":
            self.blocked_count += 1
            return False, f"Tool '{tool.name}' is danger-level, execution blocked"
        if rule["approve"] == "console":
            if self.console_approve:
                print(f"\n[PERMISSION] Tool: {tool.name}")
                print(f"  Args: {json.dumps(args, ensure_ascii=False)[:200]}")
                print(f"  Risk: {tool.risk_level}")
                resp = input("  Proceed? (y/n): ").strip().lower()
                if resp != 'y':
                    self.blocked_count += 1
                    return False, "user rejected"
            self.allowed_count += 1
            return True, "user approved"
        return False, "unknown risk level"

    def is_path_safe(self, path_str: str) -> bool:
        """检查路径是否在 allowed_root 内"""
        p = Path(path_str).resolve()
        try:
            p.relative_to(self.allowed_root)
            return True
        except ValueError:
            return False

    @property
    def summary(self) -> str:
        return (f"Sandbox: {self.allowed_count} allowed, "
                f"{self.blocked_count} blocked, "
                f"root={self.allowed_root}")


# ═══════════════════════════════════════════════════════════
# ProjectMemory — 跨 run 持久记忆
# ═══════════════════════════════════════════════════════════

class ProjectMemory:
    """跨 run 持久记忆 — 类似 Claude Code 的 CLAUDE.md，但针对验证场景

    格式: valiflow.md (放在项目根目录，Git 版本化)

    用法:
      mem = ProjectMemory("valiflow.md")
      mem.load()
      print(mem.get("constraints.axi_clk"))  # → "500MHz"
      mem.set("fi_profile.targets", ["flit_ECC", "route_parity"])
      mem.save()
    """

    def __init__(self, path: str = "valiflow.md"):
        self.path = Path(path)
        self.data: Dict[str, Any] = {
            "project": "",
            "spec": "",
            "constraints": {},
            "fi_profile": {"targets": [], "asil_target": "B"},
            "known_issues": [],
            "agent_hints": {},
        }

    def load(self) -> Dict[str, Any]:
        """从 valiflow.md 加载记忆"""
        if not self.path.exists():
            return self.data
        content = self.path.read_text(encoding="utf-8", errors="replace")

        # 解析 YAML frontmatter (---...---)
        fm_match = re.search(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if fm_match:
            import yaml
            try:
                parsed = yaml.safe_load(fm_match.group(1))
                if isinstance(parsed, dict):
                    self.data.update(parsed)
            except Exception:
                pass

        # 解析 Markdown section 中的数据
        current_section = None
        for line in content.split("\n"):
            # Section headers
            if line.startswith("## "):
                current_section = line[3:].strip().lower().replace(" ", "_")
                continue
            # known_issues: list items
            if current_section == "known_issues":
                m = re.match(r'^\s*-\s*"([^"]+)"', line)
                if m:
                    self.data.setdefault("known_issues", []).append(m.group(1))
            # constraints: key: value pairs
            if current_section == "constraints":
                m = re.match(r'^\s*-\s*(\w+):\s*(.+)$', line)
                if m:
                    self.data.setdefault("constraints", {})[m.group(1)] = m.group(2).strip()
            # fi_profile: key: value or key: [list]
            if current_section == "fi_profile":
                m = re.match(r'^\s*-\s*(\w+):\s*(.+)$', line)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    if val.startswith("[") and val.endswith("]"):
                        val = [v.strip() for v in val[1:-1].split(",")]
                    self.data.setdefault("fi_profile", {})[key] = val

        return self.data

    def save(self) -> None:
        """保存记忆到 valiflow.md"""
        import yaml
        lines = ["---"]
        # constraints
        constraints = self.data.pop("constraints", {})
        fi_profile = self.data.pop("fi_profile", {})
        known = self.data.pop("known_issues", [])

        lines.append(yaml.dump(self.data, default_flow_style=False, allow_unicode=True).rstrip())
        lines.append("---")

        # constraints section
        if constraints:
            lines.append("\n## constraints")
            for k, v in constraints.items():
                lines.append(f"  - {k}: {v}")

        # fi_profile section
        if fi_profile:
            lines.append("\n## fi_profile")
            for k, v in fi_profile.items():
                if isinstance(v, list):
                    lines.append(f"  - {k}: [{', '.join(v)}]")
                else:
                    lines.append(f"  - {k}: {v}")

        # known_issues section
        if known:
            lines.append("\n## known_issues")
            for issue in known:
                lines.append(f'  - "{issue}"')

        lines.append("")
        self.path.write_text("\n".join(lines), encoding="utf-8", errors="replace")

        # 恢复被 pop 的数据
        self.data["constraints"] = constraints
        self.data["fi_profile"] = fi_profile
        self.data["known_issues"] = known

    def get(self, path: str, default: Any = None) -> Any:
        """点号路径读取: 'constraints.axi_clk' → data['constraints']['axi_clk']"""
        keys = path.split(".")
        val = self.data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, default)
            else:
                return default
        return val

    def set(self, path: str, value: Any) -> None:
        """点号路径设置"""
        keys = path.split(".")
        d = self.data
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value

    def inject_to_context(self, ctx) -> None:
        """将记忆注入 ContextStore.Config（只读）"""
        for k, v in self.data.get("constraints", {}).items():
            ctx[f"mem.{k}"] = v
        ctx["mem.known_issues"] = self.data.get("known_issues", [])
        ctx["mem.fi_targets"] = self.data.get("fi_profile", {}).get("targets", [])


# ═══════════════════════════════════════════════════════════
# 内置验证 Tool 注册 (示例)
# ═══════════════════════════════════════════════════════════

def register_builtin_tools(registry: ToolRegistry) -> None:
    """注册内置验证工具"""

    def _handler_run_vcs(args):
        tb = args["tb"]
        top = args.get("top", "tb_top")
        cmd = f"vcs -sverilog {tb} -top {top} -debug_pp"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        return {"stdout": r.stdout[-2000:], "stderr": r.stderr[-500:], "returncode": r.returncode}

    def _handler_gen_test_sv(args):
        gap = args["gap"]
        out = args.get("out_path", f"output/testcases/test_{gap}.sv")
        template = f"// Auto-generated test for coverage gap: {gap}\n"
        template += "class test_cov_{gap}_seq extends uvm_sequence;\n"
        template += "  task body();\n"
        template += "    // TODO: implement coverage-targeted stimulus for {gap}\n"
        template += "  endtask\n"
        template += "endclass\n"
        Path(out).write_text(template.format(gap=gap), encoding="utf-8")
        return {"out_path": out, "size": len(template)}

    def _handler_read_report(args):
        path = args["path"]
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return {"content": content[:5000], "size": len(content)}

    registry.register_many([
        Tool("run_vcs",
             description="Compile and run VCS simulation for a testbench",
             input_schema={
                 "type": "object",
                 "properties": {
                     "tb": {"type": "string", "description": "Testbench .sv filename"},
                     "top": {"type": "string", "default": "tb_top", "description": "Top module name"},
                 }, "required": ["tb"],
             },
             risk_level="danger",  # VCS 调用可能吃资源, 先标 danger
             handler=_handler_run_vcs),

        Tool("gen_test_sv",
             description="Generate UVM test .sv targeting a specific coverage gap",
             input_schema={
                 "type": "object",
                 "properties": {
                     "gap": {"type": "string", "enum": ["burst_16", "outstanding_4", "cim_macro_ecc"],
                             "description": "Coverage gap identifier"},
                     "out_path": {"type": "string", "description": "Output .sv path"},
                 }, "required": ["gap"],
             },
             risk_level="write",
             handler=_handler_gen_test_sv),

        Tool("read_report",
             description="Read a verification report file (coverage, log, etc.)",
             input_schema={
                 "type": "object",
                 "properties": {
                     "path": {"type": "string", "description": "Path to report file"},
                 }, "required": ["path"],
             },
             risk_level="safe",
             handler=_handler_read_report),
    ])


# ═══════════════════════════════════════════════════════════
# ToolRegistryAdapter — 将 ToolRegistry 接入 LangChain Agent
# ═══════════════════════════════════════════════════════════

class ToolRegistryAdapter:
    """包装 LangChain @tool，在 LLM 调用时自动 Schema 验证。

    用法:
      registry = ToolRegistry()
      registry.register(Tool("gen_test_sv", input_schema={...}, handler=fn))
      adapter = ToolRegistryAdapter(registry)
      # 在 BaseAgent 中:
      #   validated_tools = adapter.wrap(agent.tools)
    """

    def __init__(self, registry: ToolRegistry, sandbox: Sandbox = None):
        self.registry = registry
        self.sandbox = sandbox
        self.stats = {"calls": 0, "schema_rejects": 0, "sandbox_blocks": 0}

    def wrap(self, langchain_tools: List) -> List:
        """包装 LangChain tools，添加 Schema 验证层。

        对于已注册到 ToolRegistry 的 tool: Schema validate → execute
        对于未注册的 tool: 保持原有行为
        """
        wrapped = []
        for lc_tool in langchain_tools:
            tool_name = getattr(lc_tool, 'name', str(lc_tool))
            registered = self.registry.get(tool_name)
            if registered:
                wrapped.append(self._create_validated_tool(lc_tool, registered))
            else:
                wrapped.append(lc_tool)  # 未注册的 tool 保持原样
        return wrapped

    def _create_validated_tool(self, lc_tool, tool_def: Tool):
        """创建带 Schema 验证的 tool wrapper"""
        from langchain.tools import tool as lc_tool_decorator
        import functools

        # 保留原 tool 的函数
        original_func = getattr(lc_tool, 'func', None) or lc_tool

        @functools.wraps(original_func if callable(original_func) else lambda x: x)
        def validated_func(input_str: str = "", **kwargs) -> str:
            self.stats["calls"] += 1

            # 尝试解析 args (可能是 JSON 字符串或 **kwargs)
            args = {}
            if input_str and isinstance(input_str, str):
                try:
                    args = json.loads(input_str)
                except json.JSONDecodeError:
                    args = {}
            args.update(kwargs)

            # Schema 验证
            ok, err = tool_def.validate_args(args)
            if not ok:
                self.stats["schema_rejects"] += 1
                return json.dumps({
                    "error": f"Schema validation failed for '{tool_def.name}': {err}",
                    "expected_schema": tool_def.input_schema,
                    "received_args": args,
                })

            # Sandbox 检查
            if self.sandbox:
                ok, err = self.sandbox.check(tool_def, args)
                if not ok:
                    self.stats["sandbox_blocks"] += 1
                    return json.dumps({"error": f"Sandbox blocked: {err}"})

            # 执行原始 tool
            try:
                if callable(original_func):
                    return original_func(input_str, **kwargs) if input_str else original_func(**kwargs)
                return str(original_func)
            except Exception as e:
                return json.dumps({"error": str(e)[:500]})

        # 创建新的 LangChain tool (保留 name, description)
        validated_tool = lc_tool_decorator(tool_def.name)(validated_func)
        validated_tool.name = tool_def.name
        validated_tool.description = tool_def.description
        return validated_tool

    @property
    def summary(self) -> str:
        return (f"ToolRegistry: {self.stats['calls']} calls, "
                f"{self.stats['schema_rejects']} schema rejects, "
                f"{self.stats['sandbox_blocks']} sandbox blocks")


def wrap_agent_tools(agent, registry: ToolRegistry = None, sandbox: Sandbox = None) -> None:
    """为 Agent 的工具添加 Schema 验证层。在 agent.initialize() 之后调用。

    用法:
      agent = VerificationArchitect()
      await agent.initialize()
      registry = ToolRegistry()
      register_builtin_tools(registry)
      # 注册 agent 特有的 tools
      registry.register(Tool("generate_uvm_from_spec", input_schema={...}, handler=fn))
      wrap_agent_tools(agent, registry)
    """
    if not registry:
        return
    adapter = ToolRegistryAdapter(registry, sandbox)
    agent.tools = adapter.wrap(agent.tools)
    # 重建 executor（如果存在）
    if hasattr(agent, '_executor') and agent._executor:
        from langchain.agents import create_openai_tools_agent, AgentExecutor
        agent_instance = create_openai_tools_agent(
            llm=agent.llm, tools=agent.tools,
            prompt=agent._get_prompt_template_sync()
        )
        agent._executor = AgentExecutor(
            agent=agent_instance, tools=agent.tools,
            verbose=getattr(agent.settings, 'agent', None) and agent.settings.agent.verbose or False,
            max_iterations=getattr(agent.settings, 'agent', None) and agent.settings.agent.max_iterations or 10,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
        )
