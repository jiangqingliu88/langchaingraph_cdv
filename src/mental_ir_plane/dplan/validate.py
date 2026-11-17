"""DPlan IR 的结构检查 —— 只报缺口，不补内容、不做语义证明。"""
from __future__ import annotations

from typing import Any, Dict, List

from .model import DesignPlan


def validate(plan: DesignPlan) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []

    def add(kind: str, message: str, severity: str = "warning", blocking: bool = False) -> None:
        issues.append({"kind": kind, "message": message,
                       "severity": severity, "blocking": blocking})

    if not plan.design_name:
        add("missing_design_name", "缺少 design_name；项目作用域无法稳定", "error", True)
    if not plan.interfaces and not plan.model_contract.ports:
        add("missing_interfaces", "interfaces 与 model_contract.ports 都为空", "warning")
    if not plan.features:
        add("missing_features", "features 为空；无法与 VPlan feature 建立关联", "warning")
    if not plan.modules:
        add("missing_modules", "modules 为空；实现层级未定义", "warning")
    if not plan.model_contract.behaviors:
        add("empty_behaviors", "model_contract.behaviors 为空；不补造行为证明", "info")
    unparsed = [s.name for s in plan.model_contract.state if not s.parsed]
    if unparsed:
        add("unparsed_state", f"{len(unparsed)} 个 model_contract.state 条目不是结构化对象；原样保留", "warning")
    if plan.embedded_vplan:
        counts = {k: (len(v) if hasattr(v, "__len__") else 1) for k, v in plan.embedded_vplan.items()}
        add("embedded_vplan_ignored",
            f"DPlan 内嵌 VPlan-like 集合保留但不作为 VPlan 权威：{counts}", "info")
    if plan.extra:
        add("extra_fields", f"未知顶层字段已保留：{sorted(plan.extra)}", "info")

    blocking = any(i["blocking"] for i in issues)
    status = "INVALID" if blocking else ("WARNING" if any(i["severity"] in ("warning", "error") for i in issues) else "READY")
    return {"schema": plan.schema, "design_name": plan.design_name,
            "status": status, "counts": plan.counts(), "issues": issues,
            "digest": plan.digest()}


__all__ = ["validate"]
