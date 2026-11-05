"""Claim 证据审计 —— 哪些结论**已经**有证据，哪些仍是候选。

这里不把“候选”当错误：CANDIDATE 是正常状态。只有
`CONFIRMED 但没有证据` / `agent 结论被当事实` 才是硬问题。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .schema import Claim


def audit_claims(claims: List[Claim],
                 evidence_index: Dict[str, Any] = None) -> Dict[str, Any]:
    index = ((evidence_index or {}).get("claims") or {})
    counts: Dict[str, int] = {}
    confirmed_without: List[str] = []
    hypotheses_confirmed: List[str] = []
    for claim in claims:
        counts[claim.status] = counts.get(claim.status, 0) + 1
        got = list(claim.evidence_ids) + list(
            (index.get(claim.claim_id) or {}).get("evidence_ids") or [])
        if claim.status == "CONFIRMED" and not got:
            confirmed_without.append(claim.claim_id)
        if claim.status == "CONFIRMED" and claim.producer_class == "agent":
            hypotheses_confirmed.append(claim.claim_id)
    return {
        "schema": "claim_audit_v1",
        "total": len(claims),
        "counts": counts,
        "candidate": counts.get("CANDIDATE", 0),
        "confirmed": counts.get("CONFIRMED", 0),
        "confirmed_without_evidence": confirmed_without,
        "hypotheses_confirmed": hypotheses_confirmed,
        "ok": not confirmed_without and not hypotheses_confirmed,
    }


__all__ = ["audit_claims"]
