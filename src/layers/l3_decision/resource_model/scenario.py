"""Resource Scenario Compiler：交互事实 → Scenario IR（不直接生成随机 sequence）。"""
from __future__ import annotations

from typing import Any, Dict, List

from .model import ResourceModel


def _expected(fact: Dict[str, Any]) -> str:
    if fact["overflow"]:
        return "checker_must_report_address_overflow"
    if fact["conflict"]:
        return "checker_must_report_forbidden_overlap"
    if fact["requires_checker"]:
        return "checker_must_verify_policy_outcome"
    return "no_conflict"


def compile_scenarios(model: ResourceModel, *,
                      address_width: int = 64) -> List[Dict[str, Any]]:
    """每条交互事实 → 一个场景；相同 (operation pair, policy, overlap) 去重。"""
    out: List[Dict[str, Any]] = []
    seen = set()
    for fact in model.interaction_facts(address_width=address_width):
        key = (fact["operation_a"], fact["operation_b"], fact["policy"],
               fact["overlap"], fact["resource_id"])
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "schema": "resource_scenario_v1",
            "scenario_id": f"SC-{fact['interaction_id']}",
            "module": model.module,
            "resource_id": fact["resource_id"],
            "operations": [fact["operation_a"], fact["operation_b"]],
            "owners": [fact["owner_a"], fact["owner_b"]],
            "accesses": [fact["access_a"], fact["access_b"]],
            "overlap": fact["overlap"],
            "policy": fact["policy"],
            "policy_id": fact["policy_id"],
            "conflict": fact["conflict"],
            "requires_checker": fact["requires_checker"],
            "expected": _expected(fact),
            "reason": fact["reason"],
            # 给序列生成器的提示：让两个操作落在同一资源/区间
            "stimulus_hint": {
                "resource_id": fact["resource_id"],
                "operation_a": fact["operation_a"],
                "operation_b": fact["operation_b"],
                "access_a": fact["access_a"],
                "access_b": fact["access_b"],
            },
            # 资源交互覆盖维度（签核时按这些格子收证据）
            "coverage": {
                "resource_pair": [fact["resource_id"],
                                  fact["resource_id"]],
                "access_relation": ("overlap" if fact["overlap"] not in
                                    ("NONE", "ADJACENT") else "non_overlap"),
                "timing_relation": ("concurrent" if fact["requires_checker"]
                                    else "unspecified"),
                "ownership": ("same_owner"
                              if fact["owner_a"] == fact["owner_b"]
                              else "different_owner"),
                "boundary": fact["overlap"],
                "conflict_outcome": ("forbidden" if fact["conflict"]
                                     else "arbitrated"
                                     if fact["requires_checker"]
                                     else "unrestricted"),
            },
        })
    return out


def coverage_summary(scenarios: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for scenario in scenarios:
        outcome = str((scenario.get("coverage") or {}).get("conflict_outcome")
                      or "")
        if outcome:
            counts[outcome] = counts.get(outcome, 0) + 1
    return counts


__all__ = ["compile_scenarios", "coverage_summary"]
