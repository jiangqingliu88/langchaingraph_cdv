"""Intent 结构校验（不阻断生成，只产出读数）。"""
from __future__ import annotations

from typing import Any, Dict, List

from .schema import IntentStatus, VerificationIntent


def validate(intents: List[VerificationIntent]) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    seen = set()
    for intent in intents:
        if not intent.case_id:
            errors.append({"rule": "missing_case", "target": intent.intent_id,
                           "message": "intent 缺 case_id"})
        if not intent.goals:
            errors.append({"rule": "empty_goals", "target": intent.intent_id,
                           "message": "intent 没有任何 goal —— 语义映射为空"})
        if intent.intent_id in seen:
            errors.append({"rule": "duplicate_intent",
                           "target": intent.intent_id,
                           "message": "同一 intent_id 出现多次"})
        seen.add(intent.intent_id)
        if intent.status == IntentStatus.CONFIRMED.value \
                and not (intent.confirmed_by or intent.evidence_ids):
            errors.append({"rule": "confirmed_without_basis",
                           "target": intent.intent_id,
                           "message": "CONFIRMED 但既无审批人也无证据"})
    return {"schema": "intent_validation_v1", "ok": not errors,
            "errors": errors, "total": len(intents)}


__all__ = ["validate"]
