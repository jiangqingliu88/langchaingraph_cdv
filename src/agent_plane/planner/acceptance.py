"""Acceptance —— 用证据判断“任务是否真的完成”，不靠模型自述。"""
from __future__ import annotations

from typing import Any, Dict, List


def acceptance_met(goal: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    regression = (evidence.get("regression") or {})
    if isinstance(regression, dict):
        status = str(regression.get("status") or "")
        if status and status != "PASS":
            reasons.append(f"regression={status}")
    elif isinstance(regression, str) and regression and regression != "PASS":
        reasons.append(f"regression={regression}")
    target = float(goal.get("target") or 0)
    coverage = (evidence.get("coverage") or {})
    if isinstance(coverage, dict) and target > 0:
        got = float(coverage.get("functional_pct") or 0)
        if got < target:
            reasons.append(f"coverage {got}% < target {target}%")
    if evidence.get("eda_missing"):
        reasons.append("EDA_MISSING")
    questions = list((evidence.get("open_questions") or []))
    if questions:
        reasons.append(f"{len(questions)} open question(s)")
    return {"met": not reasons, "reasons": reasons}


__all__ = ["acceptance_met"]
