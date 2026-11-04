"""L5 覆盖 / 义务闭环 —— 缺口、动作候选与确定性规划。"""
from src.core.metrics.engineering import collect as engineering_metrics
from src.layers.l3_decision.evidence.coverage_holes import (
    build_coverage_holes, write_coverage_holes,
)

from .actions import (
    ActionCandidate, any_candidates, from_coverage_holes, from_obligations,
)
from .loop import plan_next, should_continue

__all__ = [
    "ActionCandidate", "any_candidates", "build_coverage_holes",
    "engineering_metrics", "from_coverage_holes", "from_obligations",
    "plan_next", "should_continue", "write_coverage_holes",
]
