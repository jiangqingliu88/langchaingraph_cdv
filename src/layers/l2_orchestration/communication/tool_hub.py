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
import types
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Type

import structlog

from src.layers.l2_orchestration.communication.tool_protocol import (
    ITool, ToolManifest, ToolResult, ExecutionContext, ExecutionMode,
    ToolRisk, ToolStatus, ToolCallRecord, ToolAuditor, ToolWrapper,
)

logger = structlog.get_logger()


def _run_sync(coro):
    """在同步代码里跑一个协程，**已在事件循环中也安全**。

    直接 `asyncio.run(coro)` 在已有循环里会
    `RuntimeError: asyncio.run() cannot be called from a running event loop`
    —— 实测 5 个 LC 工具就栽在这上面（它们内部自己 `asyncio.run`）。
    所以这里判断一下：没循环就直接跑，有循环就丢到另一个线程里建新循环。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


class ToolCallError(RuntimeError):
    """`call_tool` 调用失败（工具不存在 / schema 不过 / 执行报错）。"""


class ToolRegistryError(RuntimeError):
    """`EXECUTOR_TOOL_MODULES` 声明不完整 —— 启动期就失败，不等运行期静默无工具。"""


_UNSET = object()


def call_tool(name: str, args: Dict[str, Any] = None, *, context=None,
              default=_UNSET):
    """agent 调工具的统一入口 —— 走完整校验 + 审计链路，返回工具原始结果。

    为什么需要它：`src/executors/*` 原本是直接 import 工具函数调用，例如

        from src.tools.checking.assertion_tools.main import generate_sva_assertions
        sva = generate_sva_assertions(json.dumps(spec))

    **完全绕开 ToolHub** —— 于是 schema 校验、风险分级、超时、审计回执在真正
    干活的那条路上一条都不生效；它们只在 `vagent tool call` 那条没人走的路上
    生效（而那条路此前还是一调就崩）。实测 `docs/tool_receipts.jsonl` 常年 0 行，
    就是这个原因。

    用法（返回值与直接调函数一致，调用点形态基本不变）：

        sva = call_tool("generate_sva_assertions", {"specs": json.dumps(spec)})

    **失败时抛 `ToolCallError`**，不返回 None —— 保持「直接调函数出错会抛」的
    原语义，agent 现有的 try/except 与编排层的兜底都能照常接住。返回 None 的话
    调用点会变成 `json.loads(None)` 这种更难懂的崩法。
    确实想让失败静默的，显式传 `default=<值>`。

    参数名必须与工具的 schema 一致（`args_schema` 推导而来）。**类型也要对**：
    schema 声明 `string` 的字段传 `Path` 会被 schema 校验拒绝，所以路径要 `str()`。
    """
    hub = ToolHub.get_instance()
    if not hub._initialized:
        hub.bootstrap()
    try:
        result = _run_sync(hub.invoke(name, args or {}, context))
    except Exception as e:                       # invoke 内部已尽量兜底，这里防漏
        if default is not _UNSET:
            logger.warning(f"call_tool('{name}') 异常，用 default: {e}")
            return default
        raise ToolCallError(f"call_tool('{name}') 异常: {type(e).__name__}: {e}") from e

    if result is None or not result.success:
        err = "工具未返回结果" if result is None else str(result.error)[:300]
        if default is not _UNSET:
            logger.warning(f"call_tool('{name}') 失败，用 default: {err}")
            return default
        raise ToolCallError(f"call_tool('{name}') 失败: {err}")

    # LC adapter 把输出包在 {"result": ...} 里；Old adapter 直接给 dict。
    if isinstance(result.data, dict) and set(result.data.keys()) == {"result"}:
        return result.data["result"]
    return result.data


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
        # 注册前把 ITool 的默认方法补齐 —— 见 `_ensure_itool`：Protocol 的默认
        # 实现不会被实现方继承，漏一个方法就会让 invoke 在运行时 AttributeError。
        tool = _ensure_itool(tool)
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

    def set_auditor(self, auditor) -> None:
        """替换工具调用审计器（用于把回执落到具体 run 的输出目录）。

        hub 是进程级单例，构造时还不知道 output_root；而只有
        `ToolAuditor.with_receipts(output_root)` 那个实例带落盘路径。
        `graph.hydrate_runtime` 建好它之后调这里装上，工具调用回执才会真的
        写进 `<output>/docs/tool_receipts.jsonl`。
        """
        if auditor is not None:
            self._auditor = auditor

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

        # 命令白名单（默认 monitor：只记录，不拦）。真正的 EDA 进程由
        # `src/core/jobs/supervisor.py` 管；这里先把"工具参数里夹了命令"的调用记下来。
        cmd_decision = ""
        try:
            from src.core.jobs.allowlist import scan_tool_args
            cmd_ok, cmd_reason = scan_tool_args(name, args)
            if not cmd_ok:
                record = ToolCallRecord(
                    tool_name=name, tool_version=manifest.version,
                    args_summary=str(args)[:200], success=False,
                    error=f"Command policy: {cmd_reason}",
                    timestamp=datetime.now().isoformat(), run_id=ctx.run_id,
                    manifest_hash=manifest.hash, sandbox_decision="cmd_denied",
                )
                self._auditor.record(record)
                return ToolResult.fail(f"Command policy: {cmd_reason}")
            if cmd_reason:
                cmd_decision = "cmd_monitor"
        except Exception:                     # noqa: BLE001 白名单是增强
            pass

        # Sandbox
        sandbox_decision = cmd_decision or "auto"
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
                # **来源凭证随回执落盘** —— 否则审计只能看到 success=True，
                # 分不清是 EDA 验过的还是调用方自述的。
                verified_by=getattr(result, "verified_by", "none"),
                evidence_ref=getattr(result, "evidence_ref", ""),
                returncode=getattr(result, "returncode", None),
            )
            self._auditor.record(record)
            try:
                from src.core.runtime.events import emit
                emit("tool.invoked", status="ok", source="toolhub",
                     payload={"tool": name, "verified_by": record.verified_by,
                              "evidence_ref": record.evidence_ref,
                              "sandbox_decision": sandbox_decision})
            except Exception:                 # noqa: BLE001 事件是观测
                pass
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
            try:
                from src.core.runtime.events import emit
                emit("tool.invoked", status="failed", source="toolhub",
                     payload={"tool": name, "error": str(e)[:200],
                              "sandbox_decision": sandbox_decision})
            except Exception:                 # noqa: BLE001
                pass
            return ToolResult.fail(str(e)[:500], execution_time_s=round(elapsed, 3))

    # ═══════════════════════════════════════════════════════════
    # LLM 集成
    # ═══════════════════════════════════════════════════════════

    def get_llm_tools(self, agent_role: str = None, risk_limit: ToolRisk = None) -> List[dict]:
        """获取 LLM function-calling 格式的工具列表

        角色解析走 `_tool_names_for`：**认得的 executor 精确取**
        （`EXECUTOR_TOOL_MODULES`，可能是空 —— 声明了不用工具就是没有）；
        **不认识的角色**才回退到全部，并留一条 warning。
        """
        if agent_role:
            names = self._tool_names_for(agent_role)
            if names is None:
                logger.warning(
                    f"agent {agent_role!r} 不在 `EXECUTOR_TOOL_MODULES` 里 —— 回退到全部 "
                    f"{len(self._manifests)} 个（含 WRITE/DANGER）。"
                    f"要收紧就把这个角色加进那张映射表。"
                )
                manifests = list(self._manifests.values())
            else:
                manifests = [self._manifests[n] for n in names if n in self._manifests]
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
        """为 Agent 包装工具为 LangChain tools。

        如果 Agent 已有 @tool 装饰的工具（existing_tools），也会一并包装。

        **角色解析走 `_tool_names_for`**（`EXECUTOR_TOOL_MODULES` 那张表）——
        原先注册用模块名、调用用 executor 名，两套名字之间没有桥，8 个里只有
        `coverage` / `debug` 碰巧同名，其余每次回退到全部工具（含 WRITE/DANGER），
        "白名单"形同虚设。现在认得的 executor 精确取；不认识的角色才回退并出声。
        """
        wrapped = []

        # 包装 ITool 注册的工具
        names = self._tool_names_for(agent_role)
        if names is None:
            logger.warning(
                f"executor {agent_role!r} 不在 `EXECUTOR_TOOL_MODULES` 里 —— 回退到 "
                f"hub 里全部 {len(self._tools)} 个。把角色加进那张表即可收紧。"
            )
            bound = list(self._tools.keys())
        else:
            bound = [n for n in names if n in self._tools]
        for name in bound:
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

        # 注册回归工具族的**原生 ITool**（regression.run / coverage.collect /
        # regression.reference_finder）。它们 manifest 完整、确实是 ITool，
        # 但此前**只在 tool_subprocess 的子进程 worker 里懒注册** —— 正式清单里
        # 查不到，`vagent tool list/show` 也就看不见，更不会被审计覆盖。
        # 与 read_file 那批「定义了却注册不上」是同一类问题。
        try:
            from src.layers.l2_orchestration.regression_tools.regression_tool import (
                RegressionRunTool, CoverageCollectTool, ReferenceFinderTool)
            for t in (RegressionRunTool(), CoverageCollectTool(), ReferenceFinderTool()):
                if self.register(t, ["ops"]):
                    count += 1
        except Exception as e:
            logger.warning(f"Failed to load regression tools: {e}")

        # 注册 uvm_tools
        try:
            from src.tools.generation.uvm_tools.agent_tools import ensure_uvm_tool_registry
            uvm_reg = ensure_uvm_tool_registry()
            for old_tool in uvm_reg._tools.values():
                itool = _OldToolAdapter(old_tool)
                if self.register(itool, ["uvm"]):
                    count += 1
        except Exception as e:
            logger.warning(f"Failed to load uvm_tools: {e}")

        # 注册 agent_tools 中的工具 (agent_tools.py 的工具)
        try:
            from src.layers.l2_orchestration.executors.builtin_tools import register_all_tools
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

        # 注册 LangChain @tool 工具
        count += self._load_langchain_tools()

        return count

    #: **executor 角色 → 它该拿哪些模块的工具**。
    #:
    #: 注册时绑的是**模块名**（`assert` / `spec` / `uvm` …），而调用方给的是
    #: **executor 角色**（`verify` / `design` / `ops` …）。两套名字此前没有桥，
    #: 于是 8 个 executor 里只有 `coverage` / `debug` 两个碰巧同名 —— 其余每次
    #: 都走"没有绑定 → 回退到**全部**工具（含 WRITE/DANGER）"。白名单形同虚设。
    #:
    #: 表**建在实测用量上**（各 executor 里 `call_tool(...)` 的名字落在哪个模块）：
    #:
    #:     design    analyze_specification                    → spec
    #:     verify    find_spec_yaml / jinja_render            → uvm
    #:               generate_sva_assertions                  → assert
    #:     debug     collect_sim_log / auto_fix / …           → debug
    #:     coverage  （coverage_tools 的 gap 那批）            → coverage
    #:     ops       regression.run / coverage.collect / …    → ops
    #:
    #: **`ops` 那条之前是"巧合生效"的**：模块角色里也有个叫 `ops` 的
    #: （`regression.run` / `coverage.collect` / `regression.reference_finder`，
    #: 正是这个 executor 的本职工具），两套名字同名所以直接对上了。把它写成
    #: `()` 会把那几个工具**拿走** —— 那是缩减不是收紧，迁移时差点踩到。
    #: 别名不同源的角色千万别想当然按"executor 名 == 模块名"归零。
    #:
    #: **空元组 = 这个 executor 声明不用 hub 工具**（`_get_tools()` 返回 `[]`）——
    #: 它是"就是没有"，不是"没查到"，所以**不回退**。不认识的角色才回退（见
    #: `_tool_names_for`）并出声。
    EXECUTOR_TOOL_MODULES: Dict[str, tuple] = {
        "front":    (),
        "design":   ("spec",),
        "model":    (),
        "verify":   ("uvm", "assert"),
        "ops":      ("ops",),
        "coverage": ("coverage",),
        "debug":    ("debug",),
        "audit":    (),
    }

    #: **空映射是合法声明，但必须在这里显式登记。**
    #: 新增 executor 忘了配工具时，空映射会被当成“不需要工具”而静默通过 ——
    #: 这正是要防的配置遗漏。登记在这里 = 明确说“它就是不用 hub 工具”。
    EXECUTORS_WITHOUT_HUB_TOOLS = frozenset({"front", "model", "audit"})

    #: 启动期校验的完整角色表（与 8 个 executor 对齐）。
    EXPECTED_EXECUTOR_ROLES = frozenset(EXECUTOR_TOOL_MODULES)

    @classmethod
    def registry_summary(cls) -> Dict[str, tuple]:
        """角色 → 声明的工具模块（只读快照，供启动日志/测试）。"""
        return {role: tuple(mods)
                for role, mods in cls.EXECUTOR_TOOL_MODULES.items()}

    @classmethod
    def validate_registry(cls) -> Dict[str, tuple]:
        """校验角色表完整性；返回 summary。

        失败条件是**结构性的**，不看运行期是否 bootstrap 过：
          · 缺角色（新 executor 没登记）；
          · 空映射但没在 `EXECUTORS_WITHOUT_HUB_TOOLS` 里声明不用工具。
        """
        summary = cls.registry_summary()
        missing = sorted(cls.EXPECTED_EXECUTOR_ROLES - set(summary))
        if missing:
            raise ToolRegistryError(
                f"EXECUTOR_TOOL_MODULES 缺少 executor 角色: {missing}")
        empty = {r for r, mods in summary.items() if not mods}
        undeclared = sorted(empty - cls.EXECUTORS_WITHOUT_HUB_TOOLS)
        if undeclared:
            raise ToolRegistryError(
                f"以下 executor 的工具映射为空，但未登记为“不用 hub 工具”: "
                f"{undeclared}。请补映射，或加入 EXECUTORS_WITHOUT_HUB_TOOLS。")
        return summary

    @classmethod
    def format_registry_summary(cls, summary: Dict[str, tuple] = None) -> str:
        """一行启动摘要 —— 只写 stderr，不污染 `--json` 的 stdout。"""
        summary = summary if summary is not None else cls.registry_summary()
        parts = [f"{role}={'+'.join(mods) if mods else 'none'}"
                 for role, mods in summary.items()]
        return "[tool-registry] " + " · ".join(parts)

    def _tool_names_for(self, role: str) -> Optional[List[str]]:
        """executor 角色 → 工具名列表；**不认识的返回 None**（调用方据此决定回退）。

        认得的角色一律按 `EXECUTOR_TOOL_MODULES` 精确取（可能是**空列表** ——
        那表示"这个 executor 不用工具"，不是"没查到"）。两者必须分得开：
        混成一个的话，"声明了不用"会被当成"没声明"从而拿到全部工具。
        """
        modules = self.EXECUTOR_TOOL_MODULES.get(role)
        if modules is None:
            return None
        names: List[str] = []
        for m in modules:
            for n in self._by_agent.get(m, []):
                if n not in names:
                    names.append(n)
        return names

    # 此前 ToolHub 只加载 legacy Tool(...) 与 uvm_tools，这些包里的 @tool
    # 函数**从未注册过**——ToolHub 看不见它们，经 ToolHub 调用自然也是零审计。
    # 注：cmodel_tools 不在列——它只有普通函数（generate_cmodel / compile_cmodel_dpi），
    # 没有任何 @tool，故无工具可注册。
    _LC_TOOL_MODULES = (
        ("src.tools.checking.assertion_tools.main", "assert"),
        ("src.layers.l3_decision.evidence.main", "coverage"),
        ("src.executors.debug.tools.main", "debug"),
        ("src.layers.l5_evolution.docs.main", "doc"),
        # `src.tools.reuse_tools.main` **不存在** —— 这个条目每次 bootstrap 都报
        # "No module named 'src.tools.reuse_tools'" 再被 except 吞掉，只在启动
        # 日志里留一条假错误。去掉。
        ("src.layers.l3_decision.spec_tools.main", "spec"),
        # **uvm 的 9 个工具此前从未被注册**：真实实现是
        # `src/tools/generation/uvm_tools/agent_tools.py` 里的 @tool（read_file / write_file /
        # find_spec_yaml / jinja_render / check_static / check_compile /
        # check_loopback / check_health / quality_report），但这份扫描列表漏了它。
        # 于是 hub 里这些名字留的是 `agents/agent_tools.py` 中那批**没有 handler
        # 的空声明** —— 实测 read_file 等 9 个全是 handler=None，经 ToolHub 必失败，
        # 也让 `call_tool` 无法在 agent 里安全替换直调。
        # 本函数在 register_all_tools 之后跑，注册的真实实现会覆盖空声明
        # （register 遇重名会 replace）。
        ("src.tools.generation.uvm_tools.agent_tools", "uvm"),
    )

    def _load_langchain_tools(self) -> int:
        """把上述包里的 LangChain @tool 对象适配后注册进 ToolHub。"""
        import importlib
        from langchain_core.tools import BaseTool

        count = 0
        for mod_name, role in self._LC_TOOL_MODULES:
            try:
                mod = importlib.import_module(mod_name)
            except Exception as e:
                logger.warning(f"LangChain 工具包加载失败 {mod_name}: {e}")
                continue
            for attr in dir(mod):
                if attr.startswith("_"):
                    continue
                obj = getattr(mod, attr, None)
                if not isinstance(obj, BaseTool):
                    continue
                # 已注册的是**空声明**时让真实现覆盖它（见 _is_dead_declaration）；
                # 已注册的是真实现才跳过，避免两个实现互相覆盖。
                if obj.name in self._tools and not _is_dead_declaration(self._tools[obj.name]):
                    continue
                risk = ToolRisk.SAFE if attr in _LC_SAFE_TOOLS else ToolRisk.WRITE
                if self.register(_LangChainToolAdapter(obj, risk), [role]):
                    count += 1
        return count


# ═══════════════════════════════════════════════════════════════
# 向后兼容适配器
# ═══════════════════════════════════════════════════════════════

#: 只读 / 无副作用的 `@tool` —— **必须显式列出**。
#:
#: 默认方向是 **fail-safe**：不在这个集合里的一律按 `WRITE` 计。
#:
#: 为什么不是反过来（默认 SAFE + 列 WRITE）—— 那样漏登记一个写盘工具，
#: 后果是它**静默变成"自动通过"**。而那正是这里真实发生过的 bug：
#: 原来的 `_LC_WRITE_TOOLS` 列了 18 个名字，而实际有 **32** 个 `@tool`
#: （清单里还有 5 个是已经不存在的幽灵条目），于是 `write_file`（名字
#: 就叫写文件）、`jinja_render`、`quality_report`、`check_compile` 全都
#: 没被分类，按 SAFE 放行。
#:
#: 两种漏登记的代价**不对称**，所以默认值要往安全那边倒：
#:   · 漏了只读工具 → 多一次确认（烦，但无害）
#:   · 漏了写盘工具 → 静默自动通过（危险）
#:
#: 完备性由 `tests/test_tool_risk.py` 钉住 —— 新增 `@tool` 忘了归类会红。
_LC_SAFE_TOOLS = {
    # 读文件
    "read_file",
    # 纯解析 / 纯计算：只吃文本或已落盘的数据，不写盘、不起子进程
    "analyze_specification", "analyze_coverage_gaps", "analyze_assertion_coverage",
    "extract_features", "fingerprint_error", "assess_risk",
}


def _is_dead_declaration(tool: Any) -> bool:
    """注册项是不是「只有 schema、没有实现」的空声明。

    `agents/agent_tools.py` 里那批 `Tool("analyze_design_arch", ...)` 不带
    handler，注册后 `_OldToolAdapter.execute` 只会 `fail("has no handler")`。

    这个判断是给**注册优先级**用的：同一个名字既有空声明、又有真实实现时
    （如 `read_file`：声明在 agents/agent_tools.py，实现在
    uvm_tools/agent_tools.py 的 @tool），必须让实现覆盖声明。否则谁先注册谁
    说了算，先注册的空声明会把真实现永久挡在门外。
    """
    old = getattr(tool, "_old", None)
    return old is not None and getattr(old, "handler", None) is None


def _ensure_itool(tool: Any) -> Any:
    """给注册的工具补齐 ITool 里**有默认实现**的那几个方法。

    `ITool` 是 `Protocol` —— Python **不会**把它的默认实现
    （`check_health` / `validate_input` / `validate_args_by_schema`）继承给实现方，
    只有显式 `class X(ITool)` 才有。于是本仓三个 adapter 各漏一两个方法，而
    `ToolHub.invoke` 无条件调用它们：

      · `_LangChainToolAdapter` 缺 validate_args_by_schema → 28 个 LC 工具一调就崩
      · `_OldToolAdapter`      缺 validate_input        → 26 个旧工具**参数合法时**才崩
                                                            （参数不合法时先被 schema 拒了，所以更隐蔽）

    实测 55 个注册工具里 54 个 invocable 即 AttributeError，只有示例插件
    `vcs_compile` 能用。这里统一补默认值，把这一类问题一次性堵死。

    `manifest` / `execute` 是**真缺就得报错**的（那是工具本身没实现），不补。
    """
    from src.layers.l2_orchestration.communication.tool_protocol import (
        ITool, validate_by_schema)
    defaults = {
        # 只补 Protocol 上确实给了默认实现的方法
        "check_health": lambda self: _async_true(),
        "validate_input": lambda self, args: _async_empty_list(),
        "validate_args_by_schema": lambda self, args: validate_by_schema(
            self.manifest.input_schema, args),
    }
    missing = []
    for name, impl in defaults.items():
        if not hasattr(tool, name):
            setattr(tool, name, types.MethodType(impl, tool))
            missing.append(name)
    if missing:
        name = getattr(getattr(tool, "manifest", None), "name", type(tool).__name__)
        logger.debug(f"Tool '{name}' 补齐了 ITool 默认方法: {', '.join(missing)}")

    # 仍然缺 manifest / execute 的，是真没实现，必须响亮
    if not isinstance(tool, ITool):
        logger.error(f"Tool '{getattr(tool, 'name', type(tool).__name__)}' 不满足 ITool 协议"
                     f"（manifest/execute 缺失），invoke 会失败")
    return tool


async def _async_true() -> bool:
    return True


async def _async_empty_list() -> list:
    return []


class _LangChainToolAdapter:
    """把 LangChain `@tool` 对象适配为 ITool。

    本仓有 49 个 @tool 函数，但 ToolHub 原先只认 legacy Tool / uvm_tools，
    于是 assertion / coverage / debug / doc / reuse / spec / cmodel 七个包
    从未注册——ToolHub 看不见它们，经此调用也就完全没有审计记录。
    """

    def __init__(self, lc_tool: Any, risk_level: ToolRisk = None):
        self._tool = lc_tool
        self._manifest = ToolManifest(
            name=lc_tool.name,
            version="1.0.0",
            description=(lc_tool.description or lc_tool.name)[:300],
            input_schema=_lc_args_to_schema(lc_tool),
            output_schema={"type": "string"},
            risk_level=risk_level or ToolRisk.SAFE,
            execution_mode=ExecutionMode.INLINE,
            tags=["builtin", "langchain"],
        )

    @property
    def manifest(self) -> ToolManifest:
        return self._manifest

    def validate_args_by_schema(self, args: Dict[str, Any]) -> tuple:
        """按自身 manifest 的 schema 校验 —— 与 ITool 的默认实现同一份逻辑。"""
        from src.layers.l2_orchestration.communication.tool_protocol import validate_by_schema
        return validate_by_schema(self._manifest.input_schema, args)

    async def validate_input(self, args: Dict[str, Any]) -> list:
        """LangChain 工具没有额外语义校验，交给 schema 那一层。"""
        return []

    async def check_health(self) -> bool:
        return True

    async def execute(self, args: Dict[str, Any], context) -> ToolResult:
        import time as _time
        t0 = _time.time()
        try:
            out = self._tool.invoke(args or {})
            return ToolResult(success=True, data={"result": out},
                              execution_time_s=round(_time.time() - t0, 3),
                              manifest_hash=self._manifest.hash)
        except Exception as e:
            return ToolResult.fail(f"{type(e).__name__}: {str(e)[:200]}",
                                   execution_time_s=round(_time.time() - t0, 3))


def _lc_args_to_schema(lc_tool: Any) -> Dict[str, Any]:
    """从 LangChain 工具推导 input_schema（优先 args_schema，退回 args）。"""
    schema = getattr(lc_tool, "args_schema", None)
    if schema is not None:
        try:
            if hasattr(schema, "model_json_schema"):        # pydantic v2
                return schema.model_json_schema()
            if hasattr(schema, "schema"):                   # pydantic v1
                return schema.schema()
        except Exception:
            pass
    args = getattr(lc_tool, "args", None)
    props = {k: {"type": "string"} for k in args} if isinstance(args, dict) else {}
    return {"type": "object", "properties": props, "required": []}


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

    async def validate_input(self, args: Dict[str, Any]) -> list:
        """旧 Tool 没有语义校验这一层（它的 validate_args 是 schema 级的，
        已在 validate_args_by_schema 里用过）。返回空表示无额外问题。

        缺了这个方法，`ToolHub.invoke` 里的 `await tool.validate_input(args)`
        会在**参数合法**时抛 AttributeError —— 参数不合法时先被 schema 挡掉，
        所以这个坑平时看不见，一用真参数就炸。
        """
        return []
