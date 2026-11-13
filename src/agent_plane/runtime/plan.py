"""Plan mode 的小契约 —— 第一次决策必须先交计划。"""
from __future__ import annotations

from typing import Any, Dict


def extract_plan(decision: Dict[str, Any]) -> str:
    return str(decision.get("plan") or "").strip()


def plan_required_message() -> str:
    return "PLAN_REQUIRED：第一次响应必须包含 plan"


def plan_summary(plan: str, limit: int = 600) -> str:
    text = " ".join(str(plan or "").split())
    return text[:limit]
