"""execution 的模块级辅助（Phase 4 拆分）。"""
from __future__ import annotations
import time, json, uuid, asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from src.layers.l1_infrastructure.output_config import make_output_root
from src.layers.l2_orchestration.regression_tools import sim_modes as _sim_modes

from src.layers.l2_orchestration.skills.registry import ExecutorRegistry
from config.settings import Settings

#: 执行者注册面 —— **L2 不静态 import executors**（组合根在下层/接口层）。
#: 这里用字符串路径按需加载；Phase 4 可换成外部注入的 registry。
_EXECUTOR_PATHS = {
    "front": "src.skills.front:FrontExecutor",
    "design": "src.skills.design:DesignExecutor",
    "model": "src.skills.model:ModelExecutor",
    "verify": "src.skills.verify:VerifyExecutor",
    "ops": "src.skills.ops:OpsExecutor",
    "coverage": "src.skills.coverage:CoverageExecutor",
    "debug": "src.skills.debug:DebugExecutor",
    "audit": "src.skills.audit:AuditExecutor",
}


def _new_executor(role: str):
    """按注册表路径实例化执行者（延迟 import，避免 L2 → executors 静态依赖）。"""
    import importlib

    path = _EXECUTOR_PATHS.get(role)
    if not path:
        raise KeyError(f"未知执行者角色: {role}")
    module_name, _, class_name = path.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)()

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


