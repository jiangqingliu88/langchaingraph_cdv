"""功能覆盖率纵横矩阵 IR（见同目录 `arch.md`）。"""
from .api import (load_covg_ir, matrix_of, render_covg_markdown,
                  validate_covg_text)
from .ir_core import (BinIR, ConstraintIR, CovergroupIR, CoverpointIR,
                      CovgIR, InterCrossIR, IntraCrossIR, PathIR)
from .validate import build_matrix, validate_covg

__all__ = [
    "CovgIR", "CovergroupIR", "CoverpointIR", "BinIR", "IntraCrossIR",
    "ConstraintIR", "PathIR", "InterCrossIR",
    "load_covg_ir", "validate_covg", "validate_covg_text",
    "build_matrix", "matrix_of", "render_covg_markdown",
]
