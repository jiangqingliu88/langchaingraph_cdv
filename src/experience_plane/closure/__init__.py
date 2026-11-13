"""L5 覆盖 / 义务闭环 —— 缺口、动作候选与确定性规划。

**不在这里 re-export L3 的覆盖缺口函数**：L5 不得静态依赖 L3（依赖方向门禁）。
需要 `build_coverage_holes` 的调用方直接 `from src.ir_plane.decision.evidence
import build_coverage_holes` —— 那是 L3 的职责，不是 L5 的门面。
"""
from src.runtime_plane.core.metrics.engineering import collect as engineering_metrics

from .actions import (
    ActionCandidate, any_candidates, from_coverage_holes, from_obligations,
)
from .loop import plan_next, should_continue

__all__ = [
    "ActionCandidate", "any_candidates", "engineering_metrics",
    "from_coverage_holes", "from_obligations", "plan_next", "should_continue",
]
