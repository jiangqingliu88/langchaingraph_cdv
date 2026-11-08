"""UVM 生成器入口（constraint / coverage 等独立产物）。"""
from .constraint_gen import annotate_coverage_plan, write_constraint_status
from .coverage_gen import write_coverage_plan

__all__ = [
    "write_coverage_plan", "write_constraint_status",
    "annotate_coverage_plan",
]
