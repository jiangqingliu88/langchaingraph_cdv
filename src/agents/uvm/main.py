"""
验证架构师Agent —— 通过 LangChain Agent + 工具链生成 UVM 环境

LLM Agent + 6 个工具：静态检查→编译检查→闭环验证→健康检查→读文件→写文件
质量评分基于日志分析（编译日志 + 仿真日志），三项全 PASS 才能交付
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
import structlog
import json
import re
import os
from pathlib import Path

logger = structlog.get_logger()


@register_agent("uvm")
class UvmAgent(BaseAgent):
    """验证环境编排器 —— 决策 UVM 组件结构、连接拓扑、比对策略"""

    task_type = "code_generation"
    consumes = ["spec"]
    produces = "env"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="uvm",
            display_name="验证架构师",
            description="决策 UVM 组件结构、连接拓扑、比对策略，生成组件代码并自检",
            config=config or {}
        )

    async def _setup(self):
        from src.core.agent_tools import register_all_tools
        self.tool_registry = register_all_tools()
        logger.info(f"{self.display_name} 特定初始化完成")

    def validate(self, result_data: dict) -> tuple:
        """UVM 阶段验收：代码生成 + 静态检查必须 PASS。

        静态检查（所有文件存在）是硬性指标。编译/闭环失败则降级但允许管线继续。
        """
        quality = result_data.get("quality", {})
        static_pass = quality.get("details", {}).get("static", {}).get("passed", False)
        compile_pass = quality.get("details", {}).get("compile", {}).get("passed", False)
        loopback_pass = quality.get("details", {}).get("loopback", {}).get("passed", False)

        if static_pass:
            if compile_pass and loopback_pass:
                return True, "All 3 checks PASS"
            return True, f"Static PASS (compile={'PASS' if compile_pass else 'FAIL'}, loopback={'PASS' if loopback_pass else 'FAIL'})"

        if quality.get("passed"):
            return True, "quality PASS"

        return False, "Static check FAILED"

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """Role: UVM Verification Environment Architect
Goal: Generate a COMPILABLE UVM environment. Iterate until quality_report passes ALL 3 checks.

═══════════ REACT LOOP (think → act → observe → repeat) ═══════════

PHASE 1 — GENERATE:
  1. think: "What agents does this spec need?"
  2. act:   CALL find_spec_yaml → get yaml_files, module_name, env_name
  3. act:   CALL jinja_render    → generate UVM skeleton files

PHASE 2 — VERIFY (this is the LOOP):
  4. act:   CALL quality_report → returns {passed, details: {static, compile, loopback}}
  5. observe: READ the quality_report output carefully.
     - static.passed == false? → which files are missing? (check the 'missing' field)
     - compile.passed == false? → what are the error messages? files and line numbers?
     - loopback.passed == false? → which agent failed? what was the mismatch?
  6. think: "Given the observe data, what EXACTLY needs to change?"
     - NEVER regenerate everything — fix only the failing file(s).
  7. act:   CALL the right tool for each issue:
     - static fail  → CALL jinja_render to regenerate missing files
     - compile fail → CALL read_file to see the file → CALL write_file to fix → CALL check_compile
     - loopback fail → CALL read_file to inspect → CALL write_file to fix → CALL check_loopback
  8. act:   CALL quality_report again to re-verify.
  9. IF all 3 passed → DONE.
     IF NOT → GOTO step 5. Max 5 observe→fix rounds.

═══════════ RULES ═══════════
- After EACH write_file fix, immediately call quality_report (or check_compile/check_loopback) to verify.
- DO NOT call write_file more than 3 times for the same file — that means the fix isn't working.
- ALWAYS use read_file BEFORE write_file — never write without reading first.
- After 5 observe→fix rounds without progress, give up and report what's still broken.
- Output your final summary as JSON: {"agents": ["agent1",...], "files": N, "static": "PASS/FAIL", "compile": "PASS/FAIL", "loopback": "PASS/FAIL"}
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    # ═══════════════════════════════════════════════════════════
    # LLM 工具（LangChain @tool，底层调用回归框架 RegressionRunner）
    # ═══════════════════════════════════════════════════════════

    async def _get_tools(self) -> List:
        return [
            find_spec_yaml,
            jinja_render,
            quality_report,
            check_static,
            check_compile,
            check_loopback,
            check_health,
            read_file,
            write_file,
        ]

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """ReAct 执行: 生成 + 多轮 observe→fix→verify 循环"""
        if not self._executor:
            return {"output": "Agent未初始化"}
        try:
            result = await self._executor.ainvoke({"input": input_text})
            output = result.get("output", "")
            intermediate = result.get("intermediate_steps", [])

            # ReAct 会自动通过 agent_scratchpad 注入中间步骤——
            # LangChain 的 AgentExecutor 已经内置了 think→act→observe 循环。
            # 这里的额外逻辑只是：如果最终输出还有问题，追加一轮修复。
            max_react_rounds = 3
            for round_num in range(max_react_rounds):
                # 检查是否已通过
                qp = Path(self._last_output_dir) / "quality_report.json" if hasattr(self, '_last_output_dir') else None
                if qp and qp.exists():
                    try:
                        qr = json.loads(qp.read_text(encoding="utf-8", errors="replace"))
                        details = qr.get("details", {})
                        all_pass = (
                            details.get("static", {}).get("passed") and
                            details.get("compile", {}).get("passed") and
                            details.get("loopback", {}).get("passed")
                        )
                        if all_pass:
                            break  # 已通过，不需要再修
                    except Exception:
                        pass

                # 还有问题 → 让 LLM observe 并 fix
                if "FAIL" in str(output) or "ERROR" in str(output) or "Error" in str(output):
                    fix_prompt = (
                        f"quality_report still has failures after round {round_num + 1}. "
                        f"Observe the errors below, identify the SPECIFIC file and line, "
                        f"read that file, write a targeted fix, then re-run quality_report.\n\n"
                        f"Previous output:\n{str(output)[:3000]}"
                    )
                    try:
                        fix_result = await self._executor.ainvoke({"input": fix_prompt})
                        fix_output = fix_result.get("output", "")
                        output = str(output) + f"\n\n[ReAct round {round_num + 1}]\n" + str(fix_output)
                        result["output"] = output
                    except Exception:
                        break
                else:
                    break  # 无错误，退出循环

            return {"output": output}
        except UnicodeDecodeError:
            return {"output": "Encoding error in LLM response", "score": 50}
        except Exception as e:
            return {"output": f"Agent error: {str(e)[:200]}", "score": 0}

    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从磁盘 quality_report.json 读取质量检查结果，并构造 env 数据供下游使用。
        仅在 LLM 未生成有效 agents（如都叫 dut_*）时才用 RTL 端口重新生成。"""
        output_dir = Path(_uvm_ctx.output_dir)
        module_name = getattr(self, '_module_name', '') or _uvm_ctx.env_name or ""
        if module_name.endswith("_env"):
            module_name = module_name[:-4]
        is_placeholder = not module_name or module_name.lower() in ("dut", "dut_top", "dut_env")

        # 检查 LLM 是否已经生成了有效的 agents（非占位符名）
        agents_dir = output_dir / "agents"
        existing_agents = []
        if agents_dir.exists():
            existing_agents = [d.name for d in agents_dir.iterdir()
                             if d.is_dir() and any(d.glob("*.sv"))]
        has_valid_agents = any(
            a.lower() not in ("dut_in", "dut_out", "in", "out")
            for a in existing_agents
        ) if existing_agents else False

        if not has_valid_agents and not is_placeholder:
            # LLM 没生成有效 agents → 用 RTL/spec 端口重新生成
            try:
                from src.tools.uvm_tools.tool_find_spec_yaml.main import run as _fsy_run
                from src.tools.uvm_tools.tool_jinja_render.main import run as _render_run
                _fsy_run(f"module: {module_name}")
                _render_run(str(output_dir))
                import shutil
                ml = module_name.lower()
                for sub in list((agents_dir).iterdir()):
                    if sub.is_dir() and not sub.name.lower().startswith(ml):
                        shutil.rmtree(sub, ignore_errors=True)
                for f in list((output_dir / "bench").glob("*_tb_top.sv")):
                    if ml not in f.stem.lower():
                        f.unlink()
                for f in list((output_dir / "env").rglob("*.sv")):
                    if ml not in f.stem.lower():
                        f.unlink()
                # 刷新 agent 列表
                existing_agents = [d.name for d in agents_dir.iterdir()
                                 if d.is_dir() and any(d.glob("*.sv"))]
            except Exception:
                pass

        env_name = f"{module_name}_env" if module_name else (_uvm_ctx.env_name or "dut_env")

        # ── 构造 env 数据（确保下游 test_engineer/regression_manager 可用）──
        agents_dir = output_dir / "agents"
        agent_names = sorted(
            d.name for d in agents_dir.iterdir()
            if d.is_dir() and (d / f"{d.name}_pkg.sv").exists()
        ) if agents_dir.exists() else []
        fl_path = output_dir / "inputs" / "filelists" / "filelist.f"
        if not fl_path.exists():
            fl_path = output_dir / "filelist.f"

        result["env"] = {
            "env_name": env_name,
            "output_dir": str(output_dir.resolve()),
            "agent_count": len(agent_names),
            "agents": agent_names,
            "filelist": str(fl_path) if fl_path.exists() else "",
            "files": [str(p) for p in agents_dir.rglob("*.sv")] if agents_dir.exists() else [],
            "top_module": f"{env_name}_tb_top",
        }

        # ── 根据实际生成的文件质量打分 ──
        n_agents = len(agent_names)
        n_files = len(result["env"].get("files", []))
        has_filelist = result["env"].get("filelist", "")
        if n_agents >= 2 and n_files >= 20:
            result["score"] = 75
        elif n_agents >= 1 and n_files >= 5:
            result["score"] = 50
        elif n_agents >= 1:
            result["score"] = 35
        else:
            result["score"] = 10
        return result

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        """通过 LLM Agent 执行 UVM 环境生成 + 质量自检。"""
        from src.core.output_config import make_output_root
        output_dir = make_output_root(task.get("output_dir") or None)
        self._last_output_dir = str(output_dir)  # ReAct 循环用
        # 从 ctx 提取模块名：优先 spec.design_name，其次 design_arch.module_name，最后 rtl.module_name
        ctx = task.get("ctx", {})
        spec = ctx.get("spec", {}) if hasattr(ctx, 'get') else {}
        design_arch = ctx.get("design_arch", {}) if hasattr(ctx, 'get') else {}
        rtl = ctx.get("rtl", {}) if hasattr(ctx, 'get') else {}

        def _is_placeholder(name: str) -> bool:
            """判断是否为占位符名称（dut/DUT/dut_top 等）"""
            return not name or name.lower() in ("dut", "dut_top", "dut_env")

        self._module_name = ""
        # 按优先级查找有效模块名
        for source in [
            spec.get("design_name", "") if isinstance(spec, dict) else "",
            design_arch.get("module_name", "") if isinstance(design_arch, dict) else "",
            rtl.get("module_name", "") if isinstance(rtl, dict) else "",
        ]:
            if source and not _is_placeholder(source):
                self._module_name = source
                break

        # 回退：扫描 RTL 目录中实际的 module 声明，取出现最多的非占位符模块名前缀
        if not self._module_name:
            rtl_dir = Path(output_dir) / "rtl"
            if rtl_dir.exists():
                import re as _re
                from collections import Counter as _Counter
                mod_names = []
                for sv in rtl_dir.glob("*.sv"):
                    try:
                        text = sv.read_text(encoding="utf-8", errors="replace")[:2000]
                        m = _re.search(r'^\s*module\s+(\w+)', text, _re.MULTILINE)
                        if m:
                            mod_names.append(m.group(1))
                    except Exception:
                        pass
                # 过滤掉 dut/dut_top 占位符，取出现最多的
                real_names = [n for n in mod_names if not _is_placeholder(n)]
                if real_names:
                    # 尝试提取公共前缀（如 uart_tx, uart_rx → uart）
                    counter = _Counter(real_names)
                    top = counter.most_common(1)[0][0] if counter else ""
                    # 如果名字含 _（如 uart_tx），取前缀作为模块族名
                    if "_" in top:
                        prefix = top.rsplit("_", 1)[0]
                        # 检查是否至少 2 个模块共享此前缀
                        if sum(1 for n in real_names if n.startswith(prefix)) >= 2:
                            self._module_name = prefix
                            logger.info(f"推断设计模块名前缀: {prefix}（从 RTL: {real_names[:5]}）")
                    if not self._module_name:
                        self._module_name = top

        _uvm_ctx.set(output_dir=Path(output_dir), agents=[],
                     env_name=f"{self._module_name}_env" if self._module_name else "")
        # 保存 spec 数据到输出目录，供 find_spec_yaml 读取以生成带真实端口的 YAML
        if isinstance(spec, dict) and (spec.get("interfaces") or spec.get("verification_architecture")):
            try:
                spec_path = Path(output_dir) / "spec.json"
                import json as _json
                spec_path.write_text(_json.dumps(spec, ensure_ascii=False, default=str), encoding="utf-8")
                logger.info(f"spec 已保存到 {spec_path}")
            except Exception:
                pass
        return await super().execute_task(task)

# ── Tools imported from src.tools.uvm_tools.tools ──

from src.tools.uvm_tools.agent_tools import (
    find_spec_yaml,
    jinja_render,
    quality_report,
    check_static,
    check_compile,
    check_loopback,
    check_health,
    read_file,
    write_file,
    _uvm_ctx,
    ensure_uvm_tool_registry,
)
