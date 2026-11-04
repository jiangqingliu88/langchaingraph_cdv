"""Obligation Derivation —— 复用现有 contract / ledger / derive，不建平行事实系统。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .model import ObligationStatus, VerificationObligation, from_contract_obligation


def map_status(status: str) -> str:
    """现有 derive 状态 → 统一义务状态。

    · MISSING / NOT_EXECUTED = 没有证据 → OPEN（不是 FAILED）
    · PENDING_BACKEND = 后端未接 → BLOCKED
    · PROVEN → PROVEN；PARTIAL → PARTIAL
    · NOT_APPLICABLE 只有在有 waiver 时才 WAIVED，否则 UNKNOWN
    """
    status = str(status or "").upper()
    if status == "PROVEN":
        return ObligationStatus.PROVEN.value
    if status == "PARTIAL":
        return ObligationStatus.PARTIAL.value
    if status == "PENDING_BACKEND":
        return ObligationStatus.BLOCKED.value
    if status in ("MISSING", "NOT_EXECUTED", ""):
        return ObligationStatus.OPEN.value
    if status == "NOT_APPLICABLE":
        return ObligationStatus.UNKNOWN.value
    return ObligationStatus.UNKNOWN.value


#: 谓词 → 能证明"执行过但违规"的事实类型。
_VIOLATION_FACTS = {"no_fail": "sva_result", "matched": "scb_result",
                    "executed": "scb_result"}


def _fact_matches(fact: Dict[str, Any], fact_type: str, case: str,
                  oid: str) -> bool:
    if str(fact.get("type") or "") != fact_type:
        return False
    subject = fact.get("subject") or {}
    if case and str(subject.get("case") or "") != case:
        return False
    if oid and str(subject.get("id") or "") not in (oid, "aggregate"):
        return False
    return True


def _is_violation(fact: Dict[str, Any], fact_type: str) -> bool:
    value = fact.get("value") or {}
    if str(value.get("status") or "").upper() in ("FAIL", "FAILED", "MISMATCH"):
        return True
    count = value.get("fail") if fact_type == "sva_result" \
        else value.get("mismatched")
    try:
        return count is not None and int(count) > 0
    except (TypeError, ValueError):
        return False


def _violated(ob: Any, facts: List[Dict[str, Any]]) -> bool:
    """现有 derive 把"违规"折进 MISSING；这里把它识别成真正的 FAILED。

    只认**显式违规读数**（fail>0 / mismatched>0 / status=FAIL）；否则仍是
    OPEN —— "没证据"和"证据说不过"必须分开。
    """
    predicate = getattr(ob, "predicate", None)
    fact_type = _VIOLATION_FACTS.get(str(getattr(predicate, "op", "") or ""))
    if not fact_type:
        return False
    where = dict(getattr(predicate, "where", {}) or {})
    case = str(where.get("case") or "")
    oid = str(where.get("id") or "")
    return any(_fact_matches(fact, fact_type, case, oid)
               and _is_violation(fact, fact_type) for fact in facts)


def derive_obligations(contract: Any, facts: Iterable[Dict[str, Any]], *,
                       case_ids_by_tp: Optional[Dict[str, List[str]]] = None
                       ) -> List[VerificationObligation]:
    """contract + 事实 → 统一义务列表（复用现有 `derive()` 判定）。"""
    from src.layers.l3_decision.contract import compile_obligations, derive

    obligations = compile_obligations(contract)
    facts = list(facts or [])
    statuses = derive(obligations, facts)
    out: List[VerificationObligation] = []
    for ob in obligations:
        status = statuses.get(ob.obligation_id, "MISSING")
        mapped = map_status(status)
        # 执行过且明确违规 → FAILED；没有证据仍是 OPEN（不混为一谈）。
        if mapped == ObligationStatus.OPEN.value and _violated(ob, facts):
            mapped = ObligationStatus.FAILED.value
        tps = [str(t) for t in
               ((getattr(ob, "predicate", None) and ob.predicate.where or {})
                .get("tp_ids") or [])]
        out.append(from_contract_obligation(
            ob, status=mapped,
            case_id=str(getattr(ob, "case", "") or ""),
            tp_id=tps[0] if tps else "",
            reasons=[] if status == "PROVEN" else [mapped.lower()],
        ))
    return out


def summary(obligations: List[VerificationObligation]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for ob in obligations:
        counts[ob.status] = counts.get(ob.status, 0) + 1
    done = sum(1 for ob in obligations if ob.done)
    total = len(obligations)
    return {
        "total": total,
        "done": done,
        "closure_rate": round(done / total, 4) if total else 1.0,
        "counts": counts,
    }


__all__ = ["derive_obligations", "map_status", "summary"]
