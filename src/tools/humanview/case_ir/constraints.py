"""Case ↔ 约束（constraint id）的归属 —— **声明来自 coverage plan，匹配按维度**。

一条用例除了 `groups[] / sva[] / scb[]`，还要能回答"**它的激励受哪些约束塑造**"。
约束本体由 `build_constraint` 从 case 模型生成（`p_<theme>_<method>` 策略名），
`coverage/coverage_plan.yaml#constraint_backing` 登记了每条策略负责的维度与
是否真的编译进了模型（`backed`）。

这里只做**归属**，不生成约束、不判执行：

    policy.dimensions ∩ case.dimensions（含 CG- 组名反推）→ constraints[]

**没有交集就空列表** —— 不按命名猜、不给每条 case 挂全量策略。空是事实，
视图里显示"无"比显示一个假 id 强。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _norm_dim(value: Any) -> str:
    text = str(value or "").strip()
    if text.upper().startswith("CG-"):
        text = text[3:]
    return text.lower()


def policy_index(coverage_plan: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """`coverage_plan.constraint_backing.policies` → `{policy_id: {backed, ...}}`。"""
    backing = (coverage_plan or {}).get("constraint_backing") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for item in backing.get("policies") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        out[str(item["name"])] = {
            "backed": bool(item.get("backed")),
            "dimensions": [str(d) for d in item.get("dimensions") or []],
            "reason": str(item.get("reason") or ""),
        }
    return out


def _dimension_policies(index: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    by_dim: Dict[str, List[str]] = {}
    for policy_id, meta in index.items():
        for dim in meta.get("dimensions") or []:
            by_dim.setdefault(_norm_dim(dim), []).append(policy_id)
    return by_dim


def case_dimensions(case: Dict[str, Any]) -> Iterable[str]:
    """case 的维度：显式 `dimensions` + 组名 `CG-<dim>` 反推。"""
    seen: List[str] = []
    for dim in case.get("dimensions") or []:
        if str(dim) and str(dim) not in seen:
            seen.append(str(dim))
    for group in case.get("groups") or []:
        if not isinstance(group, dict):
            continue
        gid = str(group.get("group") or "")
        if gid.upper().startswith("CG-") and gid[3:] not in seen:
            seen.append(gid[3:])
    return seen


def constraints_for(case: Dict[str, Any],
                    by_dim: Dict[str, List[str]]) -> List[str]:
    found = {pid for dim in case_dimensions(case)
             for pid in by_dim.get(_norm_dim(dim), [])}
    return sorted(found)


def attach_constraints(case_ir: Dict[str, Any],
                       coverage_plan: Dict[str, Any]) -> Dict[str, Any]:
    """就地把约束 id 写进每条 case，并带上 `constraint_backing` 注册表。

    `case_ir` 是 `CaseDoc.to_dict()` 的形状（dict）。没有 coverage plan
    （老 run / 手工 case_ir）时**不动它** —— 空列表保持"没有约束声明"。
    """
    if not isinstance(case_ir, dict):
        return case_ir
    index = policy_index(coverage_plan)
    if not index:
        return case_ir
    by_dim = _dimension_policies(index)
    for case in case_ir.get("cases") or []:
        if isinstance(case, dict):
            case["constraints"] = constraints_for(case, by_dim)
    case_ir["constraint_backing"] = index
    counts = case_ir.get("counts")
    if isinstance(counts, dict):
        counts["constraints"] = len({
            cid for c in case_ir.get("cases") or [] if isinstance(c, dict)
            for cid in c.get("constraints") or [] if cid})
    return case_ir


__all__ = [
    "attach_constraints", "case_dimensions", "constraints_for",
    "policy_index",
]
