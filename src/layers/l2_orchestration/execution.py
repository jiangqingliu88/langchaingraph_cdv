"""
Pipeline 执行服务 —— CLI 和 Web API 共享的验证流水线引擎

单例模式，管理 Agent 生命周期 + 流水线执行 + 运行状态追踪。
"""
from __future__ import annotations
import time, json, uuid, asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from src.layers.l1_infrastructure.output_config import make_output_root
from src.tools.execution.regression_tools import sim_modes as _sim_modes

from src.layers.l2_orchestration.executors.registry import ExecutorRegistry
from src.executors.design import DesignExecutor
from src.executors.front import FrontExecutor
from src.executors.model import ModelExecutor
from src.executors.verify import VerifyExecutor
from src.executors.ops import OpsExecutor
from src.executors.coverage import CoverageExecutor
from src.executors.debug import DebugExecutor
from src.executors.audit import AuditExecutor
from config.settings import Settings

logger = structlog.get_logger()


def _collect_llm_audit() -> dict:
    """收集本 run 的 LLM 调用审计（prompt 哈希 + 调用状态 + token 用量）。

    从 LLMQueryEngine 的 audit_log 读取（query_engine 记录每次调用的 cache_key =
    prompt 内容的 SHA256 前缀），落进 manifest 的 llm_audit 字段，
    支撑"同一 prompt 可复现调用"的可复现性承诺。
    失败返回空结构（不阻断 manifest 落盘）。
    """
    try:
        from src.layers.l2_orchestration.context.query_engine import LLMQueryEngine
        qe = LLMQueryEngine.get_instance()
        entries = list(getattr(qe, "audit_log", []) or [])[-50:]  # 最近 50 条
        budget = qe.get_budget_status()
        return {
            "call_count": len(entries),
            "prompt_hashes": [e.get("cache_key", "") for e in entries if e.get("cache_key")],
            "response_hashes": [e.get("response_sha", "") for e in entries if e.get("response_sha")],
            "statuses": {s: sum(1 for e in entries if e.get("status") == s)
                         for s in set(e.get("status", "") for e in entries)},
            "tokens_used": budget.get("tokens_used", 0),
            "budget": budget.get("budget", 0),
            "cache_hits": budget.get("cache_hits", 0),
        }
    except Exception as e:
        logger.warning(f"LLM 审计收集失败: {e}")
        return {"call_count": 0, "error": str(e)[:100]}

# ═══════════════════════════════════════════════════════════════
# 图流 → 运行日志的翻译
# ═══════════════════════════════════════════════════════════════
# 这三个函数的全部意义是：**把 LangGraph 的流翻译成日志，而不是往节点里插埋点**。
# `stream_mode="debug"` 给的 task / task_result 正好就是阶段的开始与结束，
# 所以「加一个节点要记得加观测」这件事根本不存在。

def _field(state: Any, name: str, default: Any = None) -> Any:
    """从 PipelineState 或它的 dict 投影里取字段 —— 两种形态都要能读。"""
    if state is None:
        return default
    if isinstance(state, dict):
        return state.get(name, default)
    return getattr(state, name, default)


def _round_of(state: Any) -> Optional[int]:
    value = _field(state, "round_num")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coverage_of(state: Any) -> Dict[str, Any]:
    """有覆盖率就返回一行摘要，没有就返回空 dict（空 dict 是 falsy，调用方据此跳过）。

    注意取的是 `effective_coverage` / `final_coverage` 两个**浮点**字段，
    不是 `coverage` —— 后者在 PipelineState 里是 `Dict[str, Any]`
    （各维度的明细），拿它当百分比会 float() 失败并静默吞掉整条覆盖率事件。
    """
    total = _field(state, "effective_coverage") or _field(state, "final_coverage") or 0
    functional = _field(state, "functional_coverage") or 0
    if not total and not functional:
        return {}
    try:
        return {"total": float(total), "functional": float(functional)}
    except (TypeError, ValueError):
        return {}


def _result_of(state: Any) -> dict:
    """终态的 result 字段 —— 与 run_closed_loop 的取法保持一致。"""
    if state is None:
        return {}
    result = (_field(state, "result") if not isinstance(state, dict)
              else state.get("result"))
    return result or {}


def _mirror_event(rt: Any, event: Any) -> None:
    """把 RunJournal 事件镜像进 EventStore（**唯一的 run/stage 事实写入点**）。

    不在节点里再写一遍 stage.* —— 图里每个节点跑两次重入就会写出重复事实。
    `_stream_run` 的 `_emit` 是唯一入口，`run_closed_loop` 只发 run.*。
    """
    store = getattr(rt, "event_store", None)
    if store is None:
        return
    kind = str(getattr(event, "kind", "") or "")
    if not kind:
        return
    try:
        store.append(
            kind,
            round=int(getattr(event, "round", 0) or 0),
            stage=str(getattr(event, "stage", "") or ""),
            agent=str(getattr(event, "agent", "") or ""),
            status=str(getattr(event, "status", "") or ""),
            payload=getattr(event, "payload", None) or {},
            source="journal",
            dedup_key=f"journal:{getattr(event, 'seq', 0)}",
        )
    except Exception as exc:                       # noqa: BLE001 观测不能带崩运行
        logger.warning(f"事件镜像失败（忽略）: {exc}")


def _translate_debug(chunk: Any, started_at: Dict[str, float], journal) -> List[Any]:
    """`stream_mode="debug"` 的一段 → 阶段开始/结束事件。

    task       → stage.started（记下墙钟，结束时算耗时）
    task_result → stage.finished / stage.failed（payload 里带 error 字段）
    """
    if not isinstance(chunk, dict):
        return []
    kind = chunk.get("type")
    payload = chunk.get("payload") or {}
    name = str(payload.get("name") or "")
    if not name:
        return []
    task_id = str(payload.get("id") or name)

    if kind == "task":
        started_at[task_id] = time.monotonic()
        return [journal.stage_started(name)]

    if kind == "task_result":
        t0 = started_at.pop(task_id, None)
        duration = (time.monotonic() - t0) if t0 is not None else 0.0
        error = payload.get("error")
        if error:
            return [journal.stage_failed(name, duration, str(error)[:500])]
        delta = payload.get("result")
        return [journal.stage_finished(name, duration,
                                       delta if isinstance(delta, dict) else None)]
    return []


def _wire_approval_events(gate: Any, journal: Any, emit: Any) -> None:
    """把审批的「问了」与「答了」接进运行日志。

    审批是**过程**的一部分：一次 REFACTOR_RTL 问过谁、等了多久、谁批的，
    都是签核时要能回答的问题。只留在内存的 records 里，进程一退就没了。

    用链式挂接而不是覆盖 —— 调用方可能已经挂了更适合的观察者。
    """
    if gate is None:
        return
    prev_request, prev_decision = gate.on_request, gate.on_decision

    def on_request(request):
        emit(journal.approval_requested(request.stage, request.risk_level,
                                        request.summary, request.token))
        if prev_request is not None:
            prev_request(request)

    def on_decision(record):
        emit(journal.approval_decided(record.decision.value, token=record.token,
                                      reason=record.reason))
        if prev_decision is not None:
            prev_decision(record)

    gate.on_request = on_request
    gate.on_decision = on_decision


def _translate_custom(chunk: Any, journal) -> List[Any]:
    """`stream_mode="custom"`：节点自己用 `get_stream_writer()` 推的细粒度进度。

    约定形状是 `{"stage": ..., "message": ...}`；不符合约定也照样记下来 ——
    丢掉一条看不懂的进度，比丢掉一条**本该看到**的进度更糟。
    """
    if isinstance(chunk, dict):
        stage = str(chunk.get("stage") or "")
        message = chunk.get("message") or chunk.get("msg")
        if message:
            extra = {k: v for k, v in chunk.items()
                     if k not in ("stage", "message", "msg")}
            return [journal.progress(stage, str(message), **extra)]
        from src.layers.l2_orchestration.run_journal import KIND_PROGRESS
        return [journal.record(KIND_PROGRESS, stage=stage, payload={"data": chunk})]
    return [journal.progress("", str(chunk)[:500])]


# ── 检查点 ─────────────────────────────────────────────────────

#: 检查点文件名。与 `run_events.jsonl` 同处 `docs/` —— 它是这次运行的**证据**
#: 的一部分（"当时停在哪个节点、为什么停"），不是临时缓存。
CHECKPOINT_FILE = "checkpoints.sqlite"


def _resolve_run_dir(output_base: str, run_id: str) -> str:
    """run_id → 那次运行的目录（找不到就原样返回基准目录）。"""
    from src.layers.l2_orchestration.run_repository import RunRepository
    found = RunRepository(output_base).run_dir(run_id)
    return str(found) if found else output_base


def _safe_checkpointer(output_root: Any):
    """`_checkpointer` 的"宁可没有也别炸"版本：开不起来就返回 None。

    检查点失效的后果是**退回通道模式**（审批阻塞等答案），而不是跑不起来 ——
    所以依赖缺失、路径不可写都吞掉，只留一条 warning。

    注意探测必须在这里做：`_checkpointer` 是 async 上下文管理器，它的函数体要
    到 `async with` 那一刻才执行，import 与 mkdir 的异常在那时才会冒出来 ——
    拿不到就来不及降级了。
    """
    try:
        import aiosqlite                                  # noqa: F401
        from langgraph.checkpoint.sqlite.aio import (     # noqa: F401
            AsyncSqliteSaver,
        )
        (Path(output_root) / "docs").mkdir(parents=True, exist_ok=True)
    except Exception as exc:                              # noqa: BLE001
        logger.warning(f"检查点不可用（运行照跑，审批退回通道模式）: {exc}")
        return None
    return _checkpointer(output_root)


@asynccontextmanager
async def _checkpointer(output_root: Any):
    """开一个运行级检查点（`docs/checkpoints.sqlite`，thread_id = run_id）。

    **必须是异步上下文管理器**：`AsyncSqliteSaver` 底下是 aiosqlite，连接绑定在
    创建它的那条 loop 上。想用"另开一个 loop 把它推起来"的办法把它塞进同步的
    `try/finally`，连接一跨 loop 就失效 —— 而且是**静默**失效（写入无声无息），
    排查起来极难。所以开合只能嵌在 async 里。

    **缺依赖时降级不阻断**：没装 `aiosqlite` 就没有检查点（审批退回通道模式），
    但验证照跑。一个可选能力不该让主流程起不来。
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    path = Path(output_root) / "docs" / CHECKPOINT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        await saver.setup()
        yield saver


def _state_of(snapshot: Any) -> Optional[Any]:
    """检查点快照 → `PipelineState`。读不出来（或不是这次运行）返回 None。

    快照的 `values` 是 dict，理论上可以直接 `model_validate`；但检查点里可能
    混着框架自己塞的键，所以先按声明过的字段筛一遍 —— `extra="forbid"` 会把
    多余的键当错误抛出来，而那不该是"重入失败"的理由。
    """
    from src.layers.l2_orchestration.state import PipelineState
    values = getattr(snapshot, "values", None)
    if not values:
        return None
    known = {k: v for k, v in dict(values).items()
             if k in PipelineState.model_fields}
    if not known.get("run_id"):
        return None
    try:
        return PipelineState.model_validate(known)
    except Exception as exc:                       # noqa: BLE001
        logger.warning(f"检查点状态读不回来: {exc}")
        return None


def _interrupt_payload(snapshot: Any) -> Dict[str, Any]:
    """快照里挂着的那个 interrupt（没有就是空 dict）。

    LangGraph 把 `interrupt()` 的内容放在 `snapshot.tasks[*].interrupts[*].value`。
    界面靠它显示"卡在哪个动作上、为什么"。
    """
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            value = getattr(item, "value", None)
            if isinstance(value, dict):
                return value
    return {}


class PipelineExecutionService:
    """流水线执行服务（单例）"""

    _instance: Optional[PipelineExecutionService] = None

    def __init__(self):
        self.settings = Settings.get_instance()
        self.registry = ExecutorRegistry.get_instance()
        self._initialized = False
        self._runs: Dict[str, dict] = {}  # run_id → {state, phases, results, ctx}

    @classmethod
    def get_instance(cls) -> PipelineExecutionService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Agent 生命周期 ──

    async def initialize_agents(self) -> None:
        """初始化所有 12 个 Agent（幂等）"""
        if self._initialized:
            return

        agents = [
            ("front",    FrontExecutor()),   # 前置分析：rtl/spec/doc → 结构化设计信息
            ("design",   DesignExecutor()),
            ("model",    ModelExecutor()),
            ("verify",   VerifyExecutor()),
            ("ops",      OpsExecutor()),
            ("coverage", CoverageExecutor()),
            ("debug",    DebugExecutor()),
            ("audit",    AuditExecutor()),
        ]
        for role, agent in agents:
            await agent.initialize()
            self.registry.set_agent_instance(role, agent)

        self._initialized = True
        logger.info("All agents initialized via PipelineExecutionService")

    @property
    def initialized(self) -> bool:
        return self._initialized

    def _relax_transaction_constraints(self, output_root: str, gaps: list):
        """放宽约束：把被 constraint 型 gap 限制的信号约束放宽到全位宽范围。

        文本级修改 agents/*/*_transaction.sv 里的 `inside {[0:MAX]}` → 全范围，
        下一轮 coverage 重新编译仿真后，高位 toggle 不再是约束型缺口。
        """
        import re
        try:
            signals = {g.get("location", "").split("[")[0]
                       for g in gaps if isinstance(g, dict) and g.get("reason") == "constraint"}
            if not signals:
                return
            for tx_file in Path(output_root).glob("agents/*/*_transaction.sv"):
                text = tx_file.read_text(encoding="utf-8", errors="replace")
                widths = {}
                for m in re.finditer(r"rand\s+bit\s*\[(\d+):0\]\s+(\w+)\s*;", text):
                    widths[m.group(2)] = int(m.group(1)) + 1
                changed = False
                for sig in signals:
                    w = widths.get(sig)
                    if not w:
                        continue
                    full_max = (1 << w) - 1
                    pat = re.compile(r"(" + re.escape(sig) + r"\s+inside\s*\{\s*\[0:)\d+(\]\s*\})")
                    text, n = pat.subn(r"\g<1>" + str(full_max) + r"\g<2>", text)
                    if n > 0:
                        changed = True
                if changed:
                    tx_file.write_text(text, encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"放宽约束失败: {e}")

    @staticmethod
    def _escalate_to_human(reason: str, action_type: str) -> str:
        """升级人工：熔断/预算耗尽时，让人工决定 retry（复位熔断）/ abort（终止）。

        返回 "retry" 或 "abort"。
        """
        try:
            from src.layers.l2_orchestration.governance.quality_guard import EscalationConsole
            decision = EscalationConsole.ask(
                f"governor:{action_type}",
                [f"驾驭层拦截: {reason}"],
                {"action_type": action_type, "reason": reason},
            )
            # EscalationConsole 返回 retry/accept_fallback/skip/abort
            return decision if decision in ("retry", "abort") else "abort"
        except Exception:
            # 终端不可用（如 CI）→ 默认 abort（终止，人工后续介入）
            return "abort"

    def _record_agent_files(self, file_audit, role: str, data: dict, params: dict = None):
        """审计证据链：记录 Agent 产出的文件（git diff + 修改理由）。

        file_audit 作为参数传入（而非 self._file_audit），保证多模块流水并发时
        各模块证据链互不污染。
        """
        if file_audit is None:
            return
        # 从 data 里提取文件列表
        files = []
        reason = ""
        for key in ("design_arch", "model", "tests", "rtl", "regression"):
            if isinstance(data.get(key), dict):
                val = data[key]
                if isinstance(val.get("files"), list):
                    files.extend(val["files"])
                elif isinstance(val.get("written_files"), list):
                    files.extend(val["written_files"])
        # 参数里的 reason（如比对失败、死代码）
        if isinstance(params, dict):
            reason = params.get("reason", "")
        recorded = 0
        for fpath in files[:10]:  # 最多记录 10 个文件
            try:
                file_audit.record(str(fpath), reason or f"{role} 产出", role)
                recorded += 1
            except Exception:
                pass
        # **增量落盘**：每跑完一个 agent 就把链刷到磁盘。原先只在最后
        # （n_finalize）落一次，中途失败/中断的 run 在 docs/ 下没有任何审计证据
        # —— 而失败时才是审计最有用的时刻。见 FileAuditTrail.save_default。
        if recorded:
            file_audit.save_default()

    @staticmethod
    def _discover_excludes(exclude_reg, gaps: list, calibration: dict = None) -> int:
        """Exclude 四步闭环·第 1 步（自动发现）：结构性不可达覆盖点 → 提议放弃。

        归因分类（第 2 步）：coverage Agent 已在归因校准阶段把"多次 refactor 仍 0%"的
        unreachable 点筛入 `calibration.blacklisted_gaps`——这些点就是结构性死代码，
        直接提议 TYPE_UNREACHABLE。"规格不测/成本高"由工程师经 CLI 手动提议。
        返回本次提议数量。
        """
        try:
            from src.layers.l4_memory.exclude_registry import TYPE_UNREACHABLE
            blacklisted = (calibration or {}).get("blacklisted_gaps", []) or []
            if not blacklisted:
                return 0
            existing = exclude_reg.get_all_points()
            proposed = 0
            for g in blacklisted:
                if not isinstance(g, dict):
                    continue
                dim = g.get("dimension", "")
                point = str(g.get("location") or g.get("signal") or dim or "unknown")
                if not point or point == "unknown" or point in existing:
                    continue
                exclude_reg.propose_exclude(
                    point,
                    reason=f"结构性死代码：{dim} 多次重构后覆盖率仍为 0%",
                    exclude_type=TYPE_UNREACHABLE,
                    evidence=f"unreachable 黑名单命中（dimension={dim}）",
                )
                existing.add(point)
                proposed += 1
            return proposed
        except Exception as e:
            logger.warning(f"Exclude 自动发现失败: {e}")
            return 0

    async def run_closed_loop(self, spec_text: str, output_root: str = "output",
                              target: Optional[float] = None, max_rounds: int = 5,
                              design_style: str = "baseline",
                              bypass_design_model: bool = False,
                              sim_modes=None, manual_gate: bool = True, rtl_dir: str = "",
                              approval_gate=None) -> dict:
        """七 Agent 闭环：design → model → verify → ops → coverage → [decision] → audit。

        控制流已由图承载（src/layers/l2_orchestration/graph.py 的 StateGraph），
        本方法只做四件事：解析入口参数 → 建运行期上下文 → 跑图 → 返回结果。

        为什么能把 626 行命令式函数换掉而不改行为：
          原函数的「共享状态」绝大部分其实是控制流（阶段顺序 + 动作分流），
          真实数据流是 _run() 的返回值；逐节点的映射见 graph.py 顶部注释。
        签名与返回结构保持不变，CLI / REPL / run_multi_module 无需改动。

        target: 覆盖率目标（None=从统一配置 Settings.verification.coverage_target 读）。
        design_style: 设计风格（baseline/pipeline/low_power）。
        bypass_design_model: True = 验证专注模式，跳过 design/model。
        approval_gate: 审批门控（None=自动；传入则高风险动作前审批）。
        """
        # 解析输出目录一次（幂等），避免每个 Agent 各自追加时间戳 → 目录不一致
        output_root = make_output_root(output_root)
        # 统一覆盖率目标来源（消除散落硬编码 95）
        if target is None:
            from src.layers.l2_orchestration.planning import get_coverage_target
            target = get_coverage_target()

        if not self._initialized:
            await self.initialize_agents()

        from src.layers.l2_orchestration.graph import (
            Runtime, build_closed_loop_graph, recursion_limit)
        from src.layers.l2_orchestration.state import PipelineState

        rt = Runtime(self, spec_text, approval_gate=approval_gate)
        graph = build_closed_loop_graph()

        # ── 外部 RTL（`--rtl <dir>`）：**两条入口都要做** ──
        # `run_closed_loop`（CLI 走这条）与 `_stream_run`（GUI/服务走那条）是两份
        # 独立实现。第一版只补了 `_stream_run` —— 于是 CLI 上 `--rtl` 被整个忽略，
        # design agent 照样生成 RTL（实测：rtl/ 里是设计产的 2 个文件、不是我给的
        # 6 个，且日志里没有「外部 RTL 已纳入」）。
        _bypass_design = False
        if rtl_dir:
            _src = Path(rtl_dir)
            if not _src.is_dir():
                logger.error(f"--rtl 指的不是目录：{rtl_dir}（按无外部 RTL 处理）")
            else:
                _dst = Path(output_root) / "rtl"
                _dst.mkdir(parents=True, exist_ok=True)
                _n = 0
                for _f in sorted(_src.rglob("*")):
                    if _f.is_file() and _f.suffix.lower() in (".sv", ".v", ".svh", ".vh"):
                        (_dst / _f.name).write_bytes(_f.read_bytes())
                        _n += 1
                logger.info(f"外部 RTL 已纳入：{_n} 个文件 ← {rtl_dir}")
                _bypass_design = True   # 只跳 design；model 照跑（它是比对的那一半）

        initial = PipelineState(
            run_id=Path(output_root).name,
            output_root=str(output_root),
            target=float(target),
            max_rounds=int(max_rounds),
            design_style=design_style,
            bypass_design_model=bool(bypass_design_model),
            bypass_design=bool(_bypass_design),
            sim_modes=list(sim_modes) if sim_modes else [
                _sim_modes.DEFAULT_MODE],
            manual_gate=bool(manual_gate),
        )
        # Architecture 2.0：这次 run 的身份 + 事实日志/产物索引/Job 运行时。
        # 失败只 warning（见 init_run_core）；真缺了会在 quality gate 的 evidence 维度看见。
        from src.layers.l2_orchestration.runtime import init_run_core
        init_run_core(rt, initial.output_root, initial.run_id)
        if rt.event_store is not None:
            rt.event_store.append(
                "run.started", status="running", source="execution",
                payload={"run_id": initial.run_id, "target": initial.target,
                         "max_rounds": initial.max_rounds,
                         "output_root": initial.output_root},
                dedup_key=f"run.started:{initial.run_id}")

        config = {
            "configurable": {"rt": rt},
            # LangGraph 数的是 superstep 而非轮次，一轮约 6-10 步
            "recursion_limit": recursion_limit(int(max_rounds)),
        }
        self._register_run(initial.run_id, output_root, spec_text)
        try:
            final = await graph.ainvoke(initial, config)
            # LangGraph 对 pydantic 状态返回模型实例；defensive 地兼容 dict
            result = (final.get("result") if isinstance(final, dict)
                      else getattr(final, "result", None))
            if rt.event_store is not None:
                rt.event_store.append(
                    "run.finished", status="completed", source="execution",
                    payload={"run_id": initial.run_id,
                             "converged": (result or {}).get("converged")},
                    dedup_key=f"run.finished:{initial.run_id}")
            self._close_run(initial.run_id, result or {})
            return result or {}
        except Exception as exc:              # noqa: BLE001
            if rt.event_store is not None:
                rt.event_store.append(
                    "run.failed", status="failed", source="execution",
                    payload={"run_id": initial.run_id,
                             "error": f"{type(exc).__name__}: {exc}"[:500]},
                    dedup_key=f"run.failed:{initial.run_id}")
            self._close_run(initial.run_id, {}, error=exc)
            raise

    async def run_closed_loop_streaming(
        self, spec_text: str, output_root: str = "output",
        target: Optional[float] = None, max_rounds: int = 5,
        design_style: str = "baseline", bypass_design_model: bool = False,
        sim_modes=None, manual_gate: bool = True, rtl_dir: str = "", approval_gate=None, on_event=None, cancel_event=None,
        run_id: str = "", checkpointing: bool = True,
        resume: Optional[str] = None,
    ) -> dict:
        """`run_closed_loop` 的可观测版本：过程写进 `docs/run_events.jsonl`。

        与 `run_closed_loop` 的差别只有一处：它用 `graph.astream(...)` 而不是
        `ainvoke`，把每个节点的开始/结束翻译成日志记录。**图与节点一行未改**
        —— 阶段边界是 LangGraph 白送的（`stream_mode="debug"` 的 task /
        task_result），不是往 23 个节点里插埋点。

        返回结构与 `run_closed_loop` 完全一致，所以调用方可以按需替换。

        on_event: 可选回调，进程内的快路径（界面直接收信号）；不传就只落盘。
        cancel_event: 可选 `threading.Event`；置位后在**下一个节点边界**退出。
            图没有检查点，所以只能停在边界上 —— 这也正是为什么取消是协作式的。

        checkpointing: 落检查点（`docs/checkpoints.sqlite`，thread_id = run_id）。
            打开之后高风险动作的审批从"阻塞等答案"变成"停下来等人"：
            `astream` 结束、运行**没有结束**，可以在另一个进程里用 `resume` 接着跑。
            缺 `aiosqlite` 时**降级为不落检查点**并告警，不阻断运行。
        resume: 重入时给出的**审批答案**（approve / reject / skip）；None = 首次跑。
            "从哪次运行继续"由 `run_id` 表达，不由这个参数表达 —— 两者混在一个
            形参里会让 `Command(resume=<run_id>)` 把 run_id 当答案喂回去。
            重入时 `output_root` 等参数以检查点里的为准。
        """
        from src.layers.l2_orchestration.run_journal import RunJournal
        from src.layers.l2_orchestration.state import PipelineState

        run_dir = _resolve_run_dir(output_root, run_id) if resume else output_root
        ctx = _safe_checkpointer(run_dir) if checkpointing else None
        if ctx is None:
            return await self._stream_run(
                spec_text=spec_text, output_root=output_root, target=target,
                max_rounds=max_rounds, design_style=design_style,
                bypass_design_model=bypass_design_model, sim_modes=sim_modes,
                manual_gate=manual_gate, rtl_dir=rtl_dir, approval_gate=approval_gate, on_event=on_event,
                cancel_event=cancel_event, run_id=run_id, saver=None,
                resume=resume)
        async with ctx as saver:
            return await self._stream_run(
                spec_text=spec_text, output_root=output_root, target=target,
                max_rounds=max_rounds, design_style=design_style,
                bypass_design_model=bypass_design_model, sim_modes=sim_modes,
                manual_gate=manual_gate, rtl_dir=rtl_dir, approval_gate=approval_gate, on_event=on_event,
                cancel_event=cancel_event, run_id=run_id, saver=saver,
                resume=resume)

    async def _stream_run(self, *, spec_text, output_root, target, max_rounds,
                          design_style, bypass_design_model, approval_gate,
                          on_event, cancel_event, run_id, saver, resume,
                          sim_modes=None, manual_gate: bool = True, rtl_dir: str = ""):
        """`run_closed_loop_streaming` 的身体 —— 拆出来只为把检查点的开合
        收进 `with`，免得流循环被 try/finally 包住看不出重点。"""
        output_root = make_output_root(output_root)
        if target is None:
            from src.layers.l2_orchestration.planning import get_coverage_target
            target = get_coverage_target()

        if not self._initialized:
            await self.initialize_agents()

        from langgraph.types import Command

        from src.layers.l2_orchestration.graph import (
            Runtime, build_closed_loop_graph, hydrate_runtime, recursion_limit)
        from src.layers.l2_orchestration.run_journal import RunJournal
        from src.layers.l2_orchestration.state import PipelineState

        resumed = resume is not None
        rt = Runtime(self, spec_text, approval_gate=approval_gate,
                     interrupt_mode=saver is not None)
        graph = build_closed_loop_graph(checkpointer=saver)

        config: Dict[str, Any] = {"configurable": {"rt": rt}}
        payload: Any = None
        if resumed:
            # 重入：状态从检查点来，LangGraph 会忽略本次传进去的输入
            config["configurable"]["thread_id"] = run_id
            snapshot = await graph.aget_state(config)
            initial = _state_of(snapshot)
            if initial is None:
                raise ValueError(f"检查点里没有 {run_id} 的状态，无法重入")
            # Runtime 里的运行期对象**必须重建**：新进程里 n_init 不会再跑，
            # 而它建的东西（engine / planner / infra / 两个注册表 / 审计链）
            # 后面每个节点都要用 —— 少了不是"退化"，是 AttributeError。
            hydrate_runtime(rt, initial)
            output_root = initial.output_root
            max_rounds = initial.max_rounds
            payload = Command(resume=resume)
        else:
            # ── 外部 RTL（`--rtl <dir>`）：用现成的，**跳过 design/model** ──
            # 验开源 IP 就走这条：把「这份 RTL 对不对」与「design agent 会不会
            # 生成 RTL」两个变量隔开。拷贝而不是就地引用 —— run 目录要能**自洽**
            # 打包（审计/复现时拿着 run 目录就能重跑，不依赖外部路径还在不在）。
            _bypass_design = False   # 未给 --rtl 时必须先有值（否则 UnboundLocalError）
            if rtl_dir:
                src = Path(rtl_dir)
                if not src.is_dir():
                    logger.error(f"--rtl 指的不是目录：{rtl_dir}（按无外部 RTL 处理）")
                else:
                    dst = Path(output_root) / "rtl"
                    dst.mkdir(parents=True, exist_ok=True)
                    _copied = 0
                    for f in sorted(src.rglob("*")):
                        if f.is_file() and f.suffix.lower() in (".sv", ".v", ".svh", ".vh"):
                            # ⚠️ **别把这个局部变量叫 `target`** —— 它是"拷到哪"，
                            # 而同名参数 `target` 是**覆盖率目标**。原来这里写成
                            # `target = dst / f.name`，把它**遮蔽**掉，于是十几行后的
                            # `PipelineState(target=float(target))` 拿到一个 Path，
                            # 当场 `TypeError`。`--rtl` 这条路上 100% 复现。
                            # （另一条路 `run_closed_loop` 写的是就地表达式，没这个坑 ——
                            # 两条路各写一遍，一边踩了另一边没踩。）
                            _dst_file = dst / f.name
                            _dst_file.write_bytes(f.read_bytes())
                            _copied += 1
                    logger.info(f"外部 RTL 已纳入：{_copied} 个文件 ← {rtl_dir}")
                    # **只跳 design，不跳 model**：外部 RTL 只省掉「生成 RTL」
                    # 那一半；参考模型（util_components 装配单）照样要生成 ——
                    # 那是比对的 expected 侧，跳了就等于什么都不验。
                    _bypass_design = True

            initial = PipelineState(
                run_id=run_id or Path(output_root).name,
                output_root=str(output_root),
                target=float(target),
                max_rounds=int(max_rounds),
                design_style=design_style,
                bypass_design_model=bool(bypass_design_model),
                bypass_design=bool(_bypass_design),
                sim_modes=list(sim_modes) if sim_modes else [
                _sim_modes.DEFAULT_MODE],
                manual_gate=bool(manual_gate),
            )
            if saver is not None:
                config["configurable"]["thread_id"] = initial.run_id
        config["recursion_limit"] = recursion_limit(int(max_rounds))

        # Architecture 2.0：身份/事实日志在 **resume 之后**建 —— 重入要用检查点
        # 里的 run_id 与 output_root，而不是本次命令行传进来的。
        from src.layers.l2_orchestration.runtime import init_run_core
        init_run_core(rt, initial.output_root, initial.run_id)

        journal = RunJournal(output_root, run_id=initial.run_id)
        if not resumed:
            self._register_run(initial.run_id, output_root, spec_text)

        def _emit(event) -> None:
            # 一个事实只写一次：RunJournal 是过程日志，EventStore 是事实日志。
            # 镜像放在这里，节点里不再重复写 stage.*。
            _mirror_event(rt, event)
            if on_event is not None:
                try:
                    on_event(event)
                except Exception as exc:      # noqa: BLE001
                    # 观察者坏了不能把运行带崩 —— 它是观测手段，不是流程的一部分
                    logger.warning(f"on_event 回调失败（忽略）: {exc}")

        _wire_approval_events(approval_gate, journal, _emit)

        result: dict = {}
        final_state: Any = None
        started_at: Dict[str, float] = {}
        last_cov: Dict[str, Any] = {}
        try:
            _emit(journal.run_resumed(resume) if resumed else journal.run_started(
                spec=Path(str(spec_text)).name[:80] or "<inline>",
                target=float(target), max_rounds=int(max_rounds),
                design_style=design_style,
                bypass_design_model=bool(bypass_design_model),
                output_root=str(output_root)))

            cancelled = False
            # 重入时传的是 `Command(resume=...)` 而不是初始状态 —— 状态已经在
            # 检查点里了，LangGraph 会忽略输入、从停下那个节点往下走。
            async for mode, chunk in graph.astream(
                    payload if resumed else initial, config,
                    stream_mode=["debug", "custom", "values"]):
                if cancel_event is not None and cancel_event.is_set():
                    _emit(journal.run_cancelled())
                    cancelled = True
                    break

                if mode == "debug":
                    for event in _translate_debug(chunk, started_at, journal):
                        _emit(event)
                elif mode == "custom":
                    for event in _translate_custom(chunk, journal):
                        _emit(event)
                else:                          # values —— 全量状态
                    final_state = chunk
                    rn = _round_of(chunk)
                    if rn is not None:
                        journal.round_num = rn
                    # values 每个节点都推一次；只在覆盖率真的变了时才记一行，
                    # 否则日志会被 80 条重复的 coverage.updated 淹掉
                    cov = _coverage_of(chunk)
                    if cov and cov != last_cov:
                        last_cov = cov
                        _emit(journal.coverage_updated(**cov))

            # 停机原因有三种，别混：
            #   收到 interrupt  → **暂停**，运行没结束，等人来答（检查点上有它）
            #   被要求取消      → 停在节点边界，就此结束
            #   正常跑完        → 出结果
            interrupted = False
            if not cancelled and saver is not None:
                snapshot = await graph.aget_state(config)
                if getattr(snapshot, "next", ()):
                    interrupted = True
                    pending = _interrupt_payload(snapshot)
                    _emit(journal.run_interrupted(
                        str(pending.get("stage", "approval")), pending))
                    result = {"interrupted": True, "pending": pending,
                              "run_id": initial.run_id}
            if not cancelled and not interrupted:
                result = _result_of(final_state)
                _emit(journal.run_finished(result))
            self._close_run(initial.run_id, result, cancelled=cancelled,
                            interrupted=interrupted)
            return result
        except Exception as exc:                # noqa: BLE001
            _emit(journal.run_failed(exc))
            self._close_run(initial.run_id, {}, error=exc)
            raise
        finally:
            journal.close()

    async def run_multi_module(self, module_specs: List[dict], output_root: str = "output",
                               target: Optional[float] = None, max_rounds: int = 5,
                               design_style: str = "baseline", max_concurrency: int = 4,
                               approval_gate=None) -> List[dict]:
        """多模块软件流水：并发跑多个闭环，EDA 等待期间互相推进（不阻塞）。

        与"多 DUT"的区别：这里的"多模块"是多个验证任务/规格的流水并行——
        模块 A 在 EDA 编译仿真（to_thread 线程里）时，模块 B 的 LLM 生成
        （design/model/verify）在事件循环里继续推进，不空转、不完全阻塞。

        module_specs: [{"name", "spec_file"|"spec_text", "target"?, "max_rounds"?, "design_style"?}, ...]
        每个模块独立 output_root/<name> + 独立证据链（FileAuditTrail 实例隔离，见 run_closed_loop）。

        返回与输入同序的结果列表（单个模块异常以 Exception 形式留在结果里）。
        """
        from src.layers.l2_orchestration.pipeline_scheduler import PipelineScheduler
        from src.layers.l1_infrastructure.output_config import make_output_root

        # 先确保 agent 初始化（避免多任务并发时重复初始化竞态）
        if not self._initialized:
            await self.initialize_agents()

        base_root = make_output_root(output_root)
        sched = PipelineScheduler(max_concurrency=max_concurrency)

        def _make_task(m: dict, idx: int):
            name = (m.get("name") or f"module_{idx + 1}").replace("/", "_").replace("\\", "_")
            spec = m.get("spec_text", "")
            if not spec and m.get("spec_file"):
                try:
                    spec = Path(m["spec_file"]).read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    spec = ""
                    logger.warning(f"模块 {name} spec 读取失败: {e}")
            # 每个模块独立带时间戳子目录（make_output_root 幂等，互不冲突）
            sub_root = make_output_root(str(Path(base_root) / name))

            async def _run():
                return await self.run_closed_loop(
                    spec_text=spec, output_root=sub_root,
                    target=m.get("target", target),
                    max_rounds=m.get("max_rounds", max_rounds),
                    design_style=m.get("design_style", design_style),
                    approval_gate=approval_gate,
                )
            return _run

        tasks = [_make_task(m, i) for i, m in enumerate(module_specs)]
        return await sched.waterfall(tasks)

    # ── 运行状态查询 ──

    def _register_run(self, run_id: str, output_root: str, spec_text: str = "") -> None:
        """把一次运行登记进内存表 —— 让 `watch` / `history` 的实时分支活过来。

        此前 `_runs` **从未被任何执行路径填充**（`get_run_status` 因此恒返回
        None），CLI 的 `watch` 只能退化到读 DB。内存表只是**加速**：
        唯一可靠来源仍然是 output 目录（见 run_repository 模块头）。
        """
        self._runs[run_id] = {
            "run_id": run_id,
            "workflow": "closed_loop_7agents",
            "state": "running",
            "current_phase": "",
            "phases": [],
            "spec": (spec_text or "")[:200],
            "output_root": str(output_root),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "completed_at": "",
        }

    def _touch_run(self, run_id: str, phase: str = "") -> None:
        run = self._runs.get(run_id)
        if run and phase:
            run["current_phase"] = phase

    def _close_run(self, run_id: str, result: dict,
                   error: Optional[BaseException] = None,
                   cancelled: bool = False,
                   interrupted: bool = False) -> None:
        """收尾内存表。失败 / 取消 / **暂停**都要落地 —— 状态停在 running 是误导。"""
        run = self._runs.get(run_id)
        if run is None:
            return
        if error is not None:
            run["state"] = "failed"
        elif cancelled:
            run["state"] = "cancelled"
        elif interrupted:
            # "等人" 不是"跑完了"：界面据此显示审批条而不是终态
            run["state"] = "waiting"
        else:
            run["state"] = "completed"
        run["completed_at"] = datetime.now().isoformat(timespec="seconds")
        run["phases"] = list(result.get("phases", []) or [])
        run["passed"] = result.get("passed", 0)
        run["total"] = result.get("total", 0)
        run["overall_score"] = result.get("overall_score", 0)
        run["scores"] = result.get("scores", {}) or {}
        run["governance"] = result.get("governance", {}) or {}
        if result.get("final_coverage") is not None:
            run["final_coverage"] = result.get("final_coverage")

    def get_run_status(self, run_id: str) -> Optional[dict]:
        """获取运行状态（供 SSE 轮询 / 前端查询）。优先内存，其次 DB。"""
        run = self._runs.get(run_id)
        if not run:
            return None
        return {
            "run_id": run["run_id"],
            "state": run["state"],
            "current_phase": run["current_phase"],
            "phases": run["phases"],
            "passed": run.get("passed", 0),
            "total": run.get("total", 0),
            "overall_score": run.get("overall_score", 0),
            "scores": run.get("scores", {}),
            "governance": run.get("governance", {}),
            "output_root": run.get("output_root", ""),
            "started_at": run.get("started_at", ""),
            "completed_at": run.get("completed_at", ""),
        }

    def list_runs(self) -> List[dict]:
        """列出所有运行"""
        return [
            {"run_id": r["run_id"], "workflow": r["workflow"],
             "state": r["state"], "started_at": r["started_at"]}
            for r in self._runs.values()
        ]

    # ── 单 Agent 执行 ──

    async def run_single_agent(
        self, role: str, input_text: str
    ) -> dict:
        """执行单个 Agent，返回 {success, output, error}"""
        if not self._initialized:
            await self.initialize_agents()

        agent = self.registry.get_agent_instance(role)
        if not agent:
            return {"success": False, "error": f"Agent not found: {role}"}

        task = {"ctx": {}, "input": input_text}
        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "output": r.data.get("output", "") if r.data else "",
            "error": r.error,
        }

    # ── 测试用例生成 ──

    async def generate_testcases(
        self, spec_text: str, output_dir: str = "output/testcases"
    ) -> dict:
        """运行 test_engineer Agent 生成测试用例"""
        if not self._initialized:
            await self.initialize_agents()

        ctx = {
            "spec": {"test_points": []},
            "env": {"env_name": "dut_env"},
        }

        agent = self.registry.get_agent_instance("test")
        if not agent:
            return {"success": False, "error": "test_engineer not found"}

        task = {
            "ctx": ctx,
            "input": json.dumps({
                "test_points": [],
                "env": ctx["env"],
            }),
            "output_dir": output_dir,
        }

        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "tests": r.data.get("tests", {}),
            "output": r.data.get("output", ""),
            "error": r.error,
        }
