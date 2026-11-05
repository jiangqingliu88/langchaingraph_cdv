"""覆盖率工具集（Phase 3：从 `tools/checking/coverage_tools` 迁入 L3）。

旧路径 `src.layers.l3_decision.evidence` 保留 shim，Phase 4 删除。
"""
from .main import *  # noqa: F401,F403
from .main import CoverageTools  # noqa: F401
from .case_cov import case_cov_matrix  # noqa: F401
from .cell_matrix import build_cell_matrix, write_cell_matrix  # noqa: F401
from .coverage_holes import (  # noqa: F401
    build_coverage_holes, write_coverage_holes,
)
from .tp_evidence import build_tp_evidence, write_tp_evidence  # noqa: F401

__all__ = [
    "CoverageTools", "build_cell_matrix", "build_coverage_holes",
    "build_tp_evidence", "case_cov_matrix", "write_cell_matrix",
    "write_coverage_holes", "write_tp_evidence",
]
