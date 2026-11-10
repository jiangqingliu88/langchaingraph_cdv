"""主图人工审批 —— Debug 连续返工/越权时强制挂起。

与 `n_approval` 的分工：
  · `n_approval` 在 `coverage_expert` 内按“动作风险”审批；
  · 本节点在主图按“Debug 连续返工次数”审批，避免子图自己把 5 轮全烧完。

没有 checkpointer 时不能 `interrupt()`（否则会抛到调用方）；此时记录
`auto_no_checkpoint` 并放行，但仍写 warning/状态，保证可审计。
"""
from __future__ import annotations

from typing import Any, Dict

import structlog

from src.layers.l2_orchestration.runtime import _rt

logger = structlog.get_logger()


async def n_human_review(state, config) -> Dict[str, Any]:
    if state.human_reviewed:
        return {}
    rt = _rt(config)
    payload = {
        "kind": "debug_review",
        "debug_attempts": int(getattr(state, "debug_attempts", 0) or 0),
        "round_num": int(getattr(state, "round_num", 0) or 0),
        "terminal_reason": str(getattr(state, "terminal_reason", "") or ""),
        "summary": "Debug 专家连续返工，请人工确认是否继续",
    }
    if not getattr(rt, "interrupt_mode", False):
        logger.warning("无 checkpointer，Debug 返工人工审批降级为放行（auto_no_checkpoint）")
        return {"human_reviewed": True, "human_decision": "auto_no_checkpoint"}

    from langgraph.types import interrupt

    answer = interrupt(payload)
    if isinstance(answer, dict):
        decision = str(answer.get("decision") or answer.get("action") or "continue")
    else:
        decision = str(answer or "continue")
    decision = decision.strip().lower()
    if decision in ("reject", "abort", "stop"):
        logger.warning("人工审批拒绝 Debug 继续返工 → 终止签核")
        return {"human_reviewed": True, "human_decision": decision,
                "interrupted": True, "terminal_reason": "human_rejected"}
    return {"human_reviewed": True, "human_decision": decision}


__all__ = ["n_human_review"]
