"""Case IR → 候选 Intent。**只产 CANDIDATE，不改 case_ir**。"""
from __future__ import annotations

from typing import Any, Dict, List

from .schema import Assumption, IntentGoal, IntentStatus, VerificationIntent


def _goal(kind: str, target: Any, rationale: str = "") -> IntentGoal:
    return IntentGoal(kind=kind, target=str(target or ""), rationale=rationale)


def _goals(case: Dict[str, Any]) -> List[IntentGoal]:
    goals: List[IntentGoal] = []
    for dim in case.get("dimensions") or []:
        goals.append(_goal("dimension", dim, "用例绑定的覆盖维度"))
    for group in case.get("groups") or []:
        if isinstance(group, dict) and group.get("group"):
            goals.append(_goal("coverage", group["group"], "功能覆盖率组"))
    for item in case.get("sva") or []:
        if isinstance(item, dict) and item.get("id"):
            goals.append(_goal("assertion", item["id"], "断言/时序检查"))
    for item in case.get("scb") or []:
        if isinstance(item, dict) and item.get("id"):
            goals.append(_goal("checker", item["id"], "比对/规则检查"))
    for constraint in case.get("constraints") or []:
        goals.append(_goal("evidence", constraint, "约束/策略证据"))
    return goals


def _intent(case: Dict[str, Any], module: str) -> VerificationIntent:
    cid = str(case.get("id") or "")
    source = str(case.get("source") or "case_ir")
    # 人给定/声明的用例视为已确认；结构合成的仍是候选（需人审或证据）。
    status = (IntentStatus.CANDIDATE.value if source == "synthesized"
              else IntentStatus.CONFIRMED.value)
    intent = VerificationIntent(
        case_id=cid,
        statement=str(case.get("name") or cid),
        module=module,
        source=source,
        source_span=str(case.get("source_span") or ""),
        goals=_goals(case),
        assumptions=[Assumption(text=str(a)) for a in
                     (case.get("assumptions") or []) if str(a)],
        status=status,
        confirmed_by="case_model" if status == IntentStatus.CONFIRMED.value else "",
        confidence=0.9 if status == IntentStatus.CONFIRMED.value else 0.5,
        metadata={"waivers": list(case.get("waivers") or []),
                  "not_applicable": dict(case.get("not_applicable") or {})},
    )
    return intent.seal()


def intents_from_case_ir(case_ir: Dict[str, Any], *,
                         module: str = "") -> List[VerificationIntent]:
    """每个 CASE 一条 Intent；语义映射默认是候选，不冒充事实。"""
    module = module or str(case_ir.get("module") or "")
    return [_intent(case, module) for case in (case_ir.get("cases") or [])
            if isinstance(case, dict) and case.get("id")]


__all__ = ["intents_from_case_ir"]
