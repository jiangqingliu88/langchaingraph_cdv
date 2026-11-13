"""Replan —— 出现新证据/失败时修订计划，而不是机械执行原 plan。"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .task_planner import normalize_steps

_TRIGGERS = {
    "tool_error": "工具执行失败，需要检查环境或换路径",
    "compile_failed": "编译失败，需要定位 RTL/UVM 编译问题",
    "regression_failed": "回归失败，需要从日志归因",
    "sva_failed": "SVA 断言失败，需要检查时序/驱动",
    "coverage_gap": "覆盖率缺口未闭合，需要补定向用例",
    "new_finding": "子 Agent 或工具发现新问题，需要调整计划",
    "spec_ambiguous": "spec 存在歧义，需要人工确认或补假设",
    "blocked": "当前步骤阻塞，需要换路或交还人工",
}


def should_replan(event: str) -> Tuple[bool, str]:
    reason = _TRIGGERS.get(str(event or "").lower(), "")
    return (bool(reason), reason)


def replan(plan: Dict[str, Any], reason: str,
           new_steps: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """在当前 active 步骤之后插入新步骤，并记录一次 replan。"""
    inserted = normalize_steps(new_steps)
    current = next((s for s in plan.get("steps") or []
                    if s.get("status") == "active"), None)
    if inserted and current is not None:
        for step in inserted:
            if not step.get("depends_on"):
                step["depends_on"] = [current["id"]]
        index = list(plan["steps"]).index(current) + 1
        plan["steps"][index:index] = inserted
    plan.setdefault("replans", []).append({
        "reason": str(reason),
        "after": current.get("id") if current else "",
        "inserted": [s["id"] for s in inserted],
    })
    return plan


__all__ = ["should_replan", "replan"]
