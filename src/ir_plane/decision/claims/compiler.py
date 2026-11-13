"""Intent → Claim（一条 goal 一条 claim）。证据要求按 kind 固定映射。"""
from __future__ import annotations

from typing import Any, Dict, List

from .schema import Claim

#: 每类语义目标**至少**需要哪类工具证据。没有对应证据 → claim 只能是 CANDIDATE。
EVIDENCE_BY_KIND: Dict[str, List[str]] = {
    "dimension": ["coverage_report"],
    "coverage": ["coverage_report"],
    "assertion": ["compile_result", "sva_hit"],
    "checker": ["compile_result", "scb_executed"],
    "evidence": ["tool_receipt"],
}


def claims_from_intents(intents: List[Any]) -> List[Claim]:
    claims: List[Claim] = []
    for intent in intents or []:
        producer = "human" if intent.status == "CONFIRMED" else "agent"
        for goal in intent.goals:
            claims.append(Claim(
                statement=f"{intent.case_id}: {goal.kind} {goal.target}",
                case_id=intent.case_id,
                intent_id=intent.intent_id,
                kind=goal.kind,
                subject={"target": goal.target, "module": intent.module},
                evidence_required=list(EVIDENCE_BY_KIND.get(goal.kind, [])),
                # **没有证据之前，claim 不能是 CONFIRMED**；intent 已确认只表示
                # “要测这个”被批准，不表示“已经证明”。
                status="CANDIDATE",
                producer_class=producer,
            ).seal())
    return claims


__all__ = ["EVIDENCE_BY_KIND", "claims_from_intents"]
