"""义务缺口 → 候选验证动作（确定性映射，不引入求解器）。"""
from __future__ import annotations

from typing import Any, Dict, List

from .model import ObligationStatus, VerificationObligation


def actions_for(obligation: VerificationObligation) -> List[str]:
    """根据状态 / 类型 / 原因给出候选动作。"""
    status = str(obligation.status or "")
    kind = str(obligation.obligation_type or "")
    reasons = {str(r).lower() for r in (obligation.reasons or [])}

    if status == ObligationStatus.PROVEN.value:
        return []
    if status == ObligationStatus.WAIVED.value:
        return []
    if status == ObligationStatus.FAILED.value:
        # 已观察到不符合要求的事实：先修，不生成“更多覆盖”
        return ["FIX_DESIGN_OR_MODEL", "REVIEW_CHECKER"]
    if status == ObligationStatus.BLOCKED.value:
        return ["FIX_ENVIRONMENT", "QUALIFY_REFERENCE_MODEL"]
    if status == ObligationStatus.UNKNOWN.value:
        return ["ADD_MONITOR", "ANALYZE_REACHABILITY"]

    actions: List[str] = []
    if kind == "sva":
        actions += ["GENERATE_CHECKER", "ADD_MONITOR"]
    elif kind == "scb":
        actions += ["GENERATE_CHECKER", "QUALIFY_REFERENCE_MODEL"]
    elif kind == "group_layer":
        actions += ["GENERATE_DIRECTED_TEST", "EXPAND_SEEDS"]
    else:
        actions.append("GENERATE_DIRECTED_TEST")
    if "no_stimulus" in reasons:
        actions.insert(0, "GENERATE_DIRECTED_TEST")
    if "constraint" in reasons:
        actions.insert(0, "FIX_CONSTRAINT")
    if "reachability" in reasons:
        actions.insert(0, "ANALYZE_REACHABILITY")
    return list(dict.fromkeys(actions))


def candidates(obligations: List[VerificationObligation],
               *, limit: int = 50) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ob in obligations:
        for action in actions_for(ob):
            out.append({
                "action": action,
                "obligation_id": ob.obligation_id,
                "case_id": ob.case_id or "",
                "tp_id": ob.tp_id or "",
                "priority": ob.priority or "",
                "status": ob.status,
                "type": ob.obligation_type,
            })
            if len(out) >= limit:
                return out
    return out


__all__ = ["actions_for", "candidates"]
