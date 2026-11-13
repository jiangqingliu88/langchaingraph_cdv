"""证据包附属摘要 —— recipe / StimulusPlan 的“只留界面要用的字段”。

从 `api.py` 拆出来，避免 `flow_tools/api.py` 继续膨胀（架构预算见
`config/architecture_budget.yaml`）。纯函数、无 IO。
"""
from __future__ import annotations

from typing import Any, Dict


def recipe_summary(recipe: Dict[str, Any]) -> Dict[str, Any]:
    if not recipe:
        return {}
    return {"schema": recipe.get("schema", ""),
            "tier_a": recipe.get("tier_a") or {},
            "tier_b": recipe.get("tier_b") or {}}


def stimulus_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    if not plan:
        return {}
    return {"schema": plan.get("schema", ""),
            "backend": plan.get("backend", ""),
            "sha256": plan.get("sha256", ""),
            "stats": plan.get("stats") or {}}
