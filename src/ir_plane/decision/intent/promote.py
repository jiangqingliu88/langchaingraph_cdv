"""Intent 状态迁移 —— 确认必须有**证据或审批人**，不能只改一个字段。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .schema import IntentStatus, VerificationIntent


class IntentPromotionError(ValueError):
    """缺证据/缺审批的确认请求 —— 显式失败。"""


def promote(intent: VerificationIntent, decision: str, *,
            by: str = "", evidence_ids: Iterable[str] = None
            ) -> VerificationIntent:
    decision = str(decision or "").upper()
    evidence = [str(e) for e in (evidence_ids or []) if str(e)]
    if decision not in {s.value for s in IntentStatus}:
        raise IntentPromotionError(f"未知意图状态 {decision!r}")
    if decision == IntentStatus.CONFIRMED.value and not (by or evidence):
        raise IntentPromotionError("CONFIRMED 需要审批人（by）或证据（evidence_ids）")
    if decision == IntentStatus.REJECTED.value and not by:
        raise IntentPromotionError("REJECTED 需要审批人（by）")
    intent.status = decision
    intent.confirmed_by = str(by or "")
    if evidence:
        intent.evidence_ids = sorted(set(intent.evidence_ids) | set(evidence))
    # **身份稳定**：状态迁移不换 intent_id —— goal 才是语义身份，审批状态不是。
    return intent if intent.intent_id else intent.seal()


def gate_check(intents: List[VerificationIntent]) -> Dict[str, Any]:
    """进契约前的读数：未确认 intent 不能作为已确认语义进入。"""
    pending = [i.intent_id for i in intents if not i.confirmed]
    return {"ok": not pending, "candidate": len(pending),
            "candidate_ids": pending}


__all__ = ["IntentPromotionError", "gate_check", "promote"]
