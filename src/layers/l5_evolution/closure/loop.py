"""自主验证闭环的确定性规划层（不引入 RL / LLM 决策）。

    Obligation / Coverage Hole
              │
              ▼
        ActionCandidate
              │
              ▼
        Deterministic Gate
              │
              ▼
        下一次执行计划

动作排序只按优先级 + 状态；**硬失败永远优先**，AI 建议不能覆盖。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .actions import ActionCandidate, any_candidates

#: 动作优先级（数字越小越先做）。
_ACTION_RANK = {
    "FIX_DESIGN_OR_MODEL": 0,
    "REVIEW_CHECKER": 1,
    "FIX_CONSTRAINT": 2,
    "FIX_ENVIRONMENT": 3,
    "QUALIFY_REFERENCE_MODEL": 4,
    "GENERATE_CHECKER": 5,
    "ADD_MONITOR": 6,
    "GENERATE_DIRECTED_TEST": 7,
    "EXPAND_SEEDS": 8,
    "ANALYZE_REACHABILITY": 9,
    "ANALYZE_GAP": 10,
    "FIX_MODEL_OR_NAMING": 11,
    "ADD_EVIDENCE": 12,
    "WAIT_BACKEND": 13,
}
_STATUS_RANK = {"FAILED": 0, "BLOCKED": 1, "OPEN": 2, "PARTIAL": 3}


def plan_next(obligations: List[Any], holes: Dict[str, Any], *,
              limit: int = 20) -> List[ActionCandidate]:
    candidates = any_candidates(obligations, holes)
    return sorted(
        candidates,
        key=lambda c: (_ACTION_RANK.get(c.action, 99),
                       _STATUS_RANK.get(c.reason, 9),
                       c.target),
    )[:max(0, limit)]


def should_continue(obligations: List[Any], *, closure_target: float = 1.0
                    ) -> Dict[str, Any]:
    """是否继续闭环：只看义务状态，不看覆盖率数字。"""
    total = len(obligations)
    done = sum(1 for ob in obligations if getattr(ob, "done", False))
    rate = done / total if total else 1.0
    return {"continue": rate < closure_target, "closure_rate": round(rate, 4),
            "total": total, "done": done}


__all__ = ["plan_next", "should_continue"]
