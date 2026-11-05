"""增量验证地基：RTL diff → 依赖分析 → 受影响用例 → 节省估算 → run diff。"""
from src.core.incremental.dependencies import affected_tests, load_dependency_map
from src.core.incremental.plan import build_plan, write_plan
from src.core.incremental.rtl_diff import diff_runs, snapshot
from src.core.incremental.run_diff import compare_runs, write_run_diff

__all__ = [
    "affected_tests", "load_dependency_map",
    "build_plan", "write_plan",
    "diff_runs", "snapshot",
    "compare_runs", "write_run_diff",
]
