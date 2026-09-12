"""
ToolHub — 统一工具注册中心 (Phase 1)

替代分散的 ToolRegistry + register_all_tools()，提供:
  1. 统一注册接口（ITool 协议）
  2. 工具发现（内置 + 插件 + 外部 CLI）
  3. 审计追踪
  4. LLM 工具规格生成
  5. 按 Agent/风险等级/分类过滤

用法:
  from src.layers.l2_orchestration.communication.tool_hub import ToolHub
  hub = ToolHub.get_instance()
  hub.bootstrap()
  tools_for_agent = hub.get_llm_tools("uvm")
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Type

import structlog

from src.layers.l2_orchestration.communication.tool_protocol import (
    ITool, ToolManifest, ToolResult, ExecutionContext,
    ToolRisk, ToolStatus, ToolCallRecord, ToolAuditor, ToolWrapper,
)

logger = structlog.get_logger()


class ToolHub:
    """统一工具注册中心 — 单例"""

    _instance: Optional[ToolHub] = None

    def __init__(self):
        self._tools: Dict[str, ITool] = {}          # name → ITool instance
        self._manifests: Dict[str, ToolManifest] = {}  # name → ToolManifest
        self._by_agent: Dict[str, List[str]] = {}   # agent_role → [tool_names]
        self._by_tag: Dict[str, List[str]] = {}     # tag → [tool_names]
        self._by_category: Dict[str, List[str]] = {}  # category → [tool_names]
        self._auditor = ToolAuditor()
        self._initialized = False
        self._plugin_manager = None  # lazy import

    @classmethod
    def get_instance(cls) -> ToolHub:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ═══════════════════════════════════════════════════════════
    # 注册
    # ═══════════════════════════════════════════════════════════

    def register(self, tool: ITool, agent_roles: List[str] = None) -> bool:
        """注册一个工具。

        Args:
          tool: ITool 实例
          agent_roles: 授权使用此工具的 Agent 角色列表。None 表示所有 Agent 可用。

        Returns:
          注册是否成功（重名返回 False）
        """
        manifest = tool.manifest

        # 验证 manifest
        issues = manifest.validate()
        if issues:
            logger.warning(f"Tool '{manifest.name}' manifest has issues: {issues}")
            for issue in issues:
                logger.warning(f"  - {issue}")

        # 检查重名
        if manifest.name in self._tools:
            existing = self._tools[manifest.name]
            logger.warning(f"Tool '{manifest.name}' already registered (v{existing.manifest.version}), "
                           f"replacing with v{manifest.version}")
            self.unregister(manifest.name)

        # 注册
        self._tools[manifest.name] = tool
        self._manifests[manifest.name] = manifest

        # 索引
        for tag in manifest.tags:
            self._by_tag.setdefault(tag, []).append(manifest.name)
        if manifest.category:
            self._by_category.setdefault(manifest.category, []).append(manifest.name)

        # Agent 绑定
        if agent_roles:
            for role in agent_roles:
                self._by_agent.setdefault(role, []).append(manifest.name)

        logger.info(f"Tool registered: {manifest.name} v{manifest.version} "
                     f"[{manifest.risk_level.value}] tags={manifest.tags}")
        return True

    def register_many(self, tools: List[Tuple[ITool, Optional[List[str]]]]) -> int:
        """批量注册工具。每项为 (tool, agent_roles)。返回成功注册数。"""
        count = 0
        for item in tools:
            if isinstance(item, tuple) and len(item) == 2:
                if self.register(item[0], item[1]):
                    count += 1
            else:
                if self.register(item):
                    count += 1
        return count

    def unregister(self, name: str) -> bool:
        """移除工具"""
        if name not in self._tools:
            return False
        manifest = self._tools[name].manifest
        del self._tools[name]
        del self._manifests[name]
        for tag_list in self._by_tag.values():
            if name in tag_list:
                tag_list.remove(name)
        for cat_list in self._by_category.values():
            if name in cat_list:
                cat_list.remove(name)
        for agent_list in self._by_agent.values():
            if name in agent_list:
                agent_list.remove(name)
        logger.info(f"Tool unregistered: {name}")
        return True

    # ═══════════════════════════════════════════════════════════
    # 查询
    # ═══════════════════════════════════════════════════════════

    def get(self, name: str) -> Optional[ITool]:
        return self._tools.get(name)

    def get_manifest(self, name: str) -> Optional[ToolManifest]:
        return self._manifests.get(name)

    def list_all(self) -> List[ToolManifest]:
        return list(self._manifests.values())

    def list_by_agent(self, agent_role: str) -> List[ToolManifest]:
        """获取某 Agent 可用的所有工具"""
        tool_names = self._by_agent.get(agent_role, list(self._tools.keys()))
        return [self._manifests[n] for n in tool_names if n in self._manifests]

    def list_by_tag(self, tag: str) -> List[ToolManifest]:
        names = self._by_tag.get(tag, [])
        return [self._manifests[n] for n in names if n in self._manifests]

    def list_by_category(self, category: str) -> List[ToolManifest]:
        names = self._by_category.get(category, [])
        return [self._manifests[n] for n in names if n in self._manifests]

    def list_by_risk(self, risk: ToolRisk) -> List[ToolManifest]:
        return [m for m in self._manifests.values() if m.risk_level == risk]

    def search(self, keyword: str) -> List[ToolManifest]:
        """全文搜索工具（名称 + 描述 + tags）"""
        kw = keyword.lower()
        results = []
        for m in self._manifests.values():
            if (kw in m.name.lower() or kw in m.description.lower() or
                any(kw in t.lower() for t in m.tags)):
                results.append(m)
        return results

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def categories(self) -> List[str]:
        return sorted(self._by_category.keys())

    @property
    def tags(self) -> List[str]:
        return sorted(self._by_tag.keys())

    # ═══════════════════════════════════════════════════════════
    # 执行
    # ═══════════════════════════════════════════════════════════

    async def invoke(self, name: str, args: Dict[str, Any],
                     context: ExecutionContext = None,
                     sandbox=None) -> ToolResult:
        """调用工具: schema validate → sandbox check → execute → audit"""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult.fail(f"Tool '{name}' not found. Available: {list(self._tools.keys())[:10]}")

        manifest = tool.manifest
        ctx = context or ExecutionContext()

        # Schema 验证
        ok, err = tool.validate_args_by_schema(args)
        if not ok:
            record = ToolCallRecord(
                tool_name=name, tool_version=manifest.version,
                args_summary=str(args)[:200], success=False, error=f"Schema: {err}",
                timestamp=datetime.now().isoformat(), run_id=ctx.run_id,
                manifest_hash=manifest.hash, sandbox_decision="schema_reject",
            )
            self._auditor.record(record)
            return ToolResult.fail(f"Schema validation: {err}")

        # 业务验证
        business_issues = await tool.validate_input(args)
        if business_issues:
            logger.warning(f"Tool '{name}' business validation: {business_issues}")

        # Sandbox
        sandbox_decision = "auto"
        if sandbox:
            try:
                from src.layers.l2_orchestration.communication.tool_system import Tool as OldTool
                dummy = OldTool(manifest.name, description=manifest.description,
                                input_schema=manifest.input_schema,
                                risk_level=manifest.risk_level.value)
                ok, err = sandbox.check(dummy, args)
                if not ok:
                    record = ToolCallRecord(
                        tool_name=name, tool_version=manifest.version,
                        args_summary=str(args)[:200], success=False,
                        error=f"Sandbox: {err}", timestamp=datetime.now().isoformat(),
                        run_id=ctx.run_id, manifest_hash=manifest.hash,
                        sandbox_decision="blocked",
                    )
                    self._auditor.record(record)
                    return ToolResult.fail(f"Sandbox blocked: {err}")
                sandbox_decision = err
            except Exception:
                pass

        # 执行
        start = time.monotonic()
        try:
            result = await tool.execute(args, ctx)
            elapsed = time.monotonic() - start
            result.execution_time_s = round(elapsed, 3)
            result.manifest_hash = manifest.hash

            record = ToolCallRecord(
                tool_name=name, tool_version=manifest.version,
                args_summary=str(args)[:200], success=result.success,
                error=result.error or "", execution_time_s=elapsed,
                timestamp=datetime.now().isoformat(), run_id=ctx.run_id,
                manifest_hash=manifest.hash, sandbox_decision=sandbox_decision,
            )
            self._auditor.record(record)
            return result

        except Exception as e:
            elapsed = time.monotonic() - start
            record = ToolCallRecord(
                tool_name=name, tool_version=manifest.version,
                args_summary=str(args)[:200], success=False, error=str(e)[:500],
                execution_time_s=elapsed, timestamp=datetime.now().isoformat(),
                run_id=ctx.run_id, manifest_hash=manifest.hash,
                sandbox_decision=sandbox_decision,
            )
            self._auditor.record(record)
            return ToolResult.fail(str(e)[:500], execution_time_s=round(elapsed, 3))

    # ═══════════════════════════════════════════════════════════
    # LLM 集成
    # ═══════════════════════════════════════════════════════════

    def get_llm_tools(self, agent_role: str = None, risk_limit: ToolRisk = None) -> List[dict]:
        """获取 LLM function-calling 格式的工具列表"""
        if agent_role:
            manifests = self.list_by_agent(agent_role)
            if not manifests:
                # 如果没有为 agent 绑定特定工具，返回所有
                manifests = list(self._manifests.values())
        else:
            manifests = list(self._manifests.values())

        if risk_limit:
            # 只返回风险等级 ≤ risk_limit 的工具
            risk_order = {"safe": 0, "write": 1, "danger": 2}
            manifests = [m for m in manifests
                         if risk_order.get(m.risk_level.value, 0) <= risk_order.get(risk_limit.value, 2)]

        return [m.to_llm_function_spec() for m in manifests
                if m.status == ToolStatus.ACTIVE]

    def wrap_agent_tools(self, agent_role: str, existing_tools: list = None,
                         sandbox=None, context: ExecutionContext = None) -> list:
        """为 Agent 包装所有已注册工具为 LangChain tools。

        如果 Agent 已有 @tool 装饰的工具（existing_tools），也会一并包装。
        """
        wrapped = []

        # 包装 ITool 注册的工具
        for name in self._by_agent.get(agent_role, list(self._tools.keys())):
            tool = self._tools.get(name)
            if tool and tool.manifest.status == ToolStatus.ACTIVE:
                wrapper = ToolWrapper(tool, sandbox, context)
                try:
                    lc_tool = wrapper.to_langchain_tool()
                    wrapped.append(lc_tool)
                except Exception as e:
                    logger.warning(f"Failed to wrap tool '{name}': {e}")

        # 保留原有 @tool 装饰的工具
        if existing_tools:
            wrapped.extend(existing_tools)

        return wrapped

    # ═══════════════════════════════════════════════════════════
    # 审计
    # ═══════════════════════════════════════════════════════════

    def get_history(self, tool_name: str = None, limit: int = 50) -> List[ToolCallRecord]:
        return self._auditor.query(tool_name=tool_name, limit=limit)

    def get_stats(self, tool_name: str = None) -> Dict[str, Any]:
        return self._auditor.get_stats(tool_name)

    def export_audit_log(self) -> str:
        return self._auditor.to_jsonl()

    # ═══════════════════════════════════════════════════════════
    # 健康检查
    # ═══════════════════════════════════════════════════════════

    async def health_check(self) -> Dict[str, Any]:
        """检查所有工具的健康状态"""
        results = {}
        for name, tool in self._tools.items():
            try:
                healthy = await tool.check_health()
                results[name] = {"healthy": healthy, "status": "ok" if healthy else "unhealthy"}
            except Exception as e:
                results[name] = {"healthy": False, "status": "error", "error": str(e)}
        return {
            "total": len(results),
            "healthy": sum(1 for r in results.values() if r["healthy"]),
            "unhealthy": sum(1 for r in results.values() if not r["healthy"]),
            "details": results,
        }

    # ═══════════════════════════════════════════════════════════
    # Bootstrap
    # ═══════════════════════════════════════════════════════════

    def bootstrap(self, plugin_dirs: List[str] = None,
                  load_plugins: bool = True,
                  load_cli_tools: bool = True) -> int:
        """启动时加载所有工具。

        加载顺序:
          1. 内置工具（src/tools/*/）
          2. 插件工具（~/.signoffai/plugins/, .signoffai/plugins/）
          3. 外部 CLI 工具（tool.yaml 配置）

        Returns:
          加载的工具总数
        """
        if self._initialized:
            return self.tool_count

        count = 0

        # 1. 内置工具
        count += self._load_builtin_tools()

        # 2. 插件工具
        if load_plugins:
            try:
                from src.layers.l2_orchestration.plugin_manager import PluginManager
                self._plugin_manager = PluginManager(plugin_dirs)
                discovered = self._plugin_manager.discover()
                for tool, roles in discovered:
                    if self.register(tool, roles):
                        count += 1
            except ImportError:
                logger.info("PluginManager not available — skipping plugin discovery")
            except Exception as e:
                logger.warning(f"Plugin discovery failed: {e}")

        # 3. 外部 CLI 工具
        if load_cli_tools:
            try:
                from src.layers.l2_orchestration.cli_tool_adapter import CLIToolLoader
                cli_tools = CLIToolLoader().discover()
                for tool, roles in cli_tools:
                    if self.register(tool, roles):
                        count += 1
            except ImportError:
                logger.info("CLIToolAdapter not available — skipping CLI tool discovery")
            except Exception as e:
                logger.warning(f"CLI tool discovery failed: {e}")

        self._initialized = True
        logger.info(f"ToolHub bootstrapped: {count} tools registered")
        return count

    def _load_builtin_tools(self) -> int:
        """加载内置工具（从 agent_tools.py 迁移）"""
        count = 0

        # 注册 uvm_tools
        try:
            from src.tools.uvm_tools.agent_tools import ensure_uvm_tool_registry
            uvm_reg = ensure_uvm_tool_registry()
            for old_tool in uvm_reg._tools.values():
                itool = _OldToolAdapter(old_tool)
                if self.register(itool, ["uvm"]):
                    count += 1
        except Exception as e:
            logger.warning(f"Failed to load uvm_tools: {e}")

        # 注册 agent_tools 中的工具 (agent_tools.py 的工具)
        try:
            from src.layers.l2_orchestration.agents.agent_tools import register_all_tools
            old_registry = register_all_tools()
            # 跳过 uvm tools（已注册），注册其他
            uvm_names = {"find_spec_yaml", "jinja_render", "quality_report",
                         "check_static", "check_compile", "check_loopback",
                         "check_health", "read_file", "write_file"}
            for old_tool in old_registry._tools.values():
                if old_tool.name not in uvm_names and old_tool.name not in self._tools:
                    itool = _OldToolAdapter(old_tool)
                    if self.register(itool):
                        count += 1
        except Exception as e:
            logger.warning(f"Failed to load agent_tools: {e}")

        return count


# ═══════════════════════════════════════════════════════════════
# 向后兼容适配器
# ═══════════════════════════════════════════════════════════════

class _OldToolAdapter:
    """将旧的 src.core.tool_system.Tool 适配为 ITool"""

    def __init__(self, old_tool):
        from src.layers.l2_orchestration.communication.tool_system import Tool as OldTool
        self._old: OldTool = old_tool

    @property
    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name=self._old.name,
            version="1.0.0",
            description=self._old.description,
            input_schema=self._old.input_schema,
            risk_level=ToolRisk.parse(self._old.risk_level),
        )

    async def execute(self, args: Dict[str, Any], context: ExecutionContext) -> ToolResult:
        if not self._old.handler:
            return ToolResult.fail(f"Tool '{self._old.name}' has no handler")
        try:
            result = self._old.handler(args)
            return ToolResult.ok(result if isinstance(result, dict) else {"output": str(result)})
        except Exception as e:
            return ToolResult.fail(str(e)[:500])

    async def check_health(self) -> bool:
        return self._old.handler is not None

    def validate_args_by_schema(self, args: Dict[str, Any]) -> tuple:
        return self._old.validate_args(args)
