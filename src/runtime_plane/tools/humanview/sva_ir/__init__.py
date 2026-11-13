"""SVA 分解 IR（见同目录 `arch.md`）。"""
from .api import (load_sva_ir, matrix_of, render_sva_markdown,
                  validate_sva_text)
from .ir_core import SVA_CLASSES, SVADoc, SVAIR, norm_class
from .validate import build_matrix, sva_status, validate_sva

__all__ = [
    "SVADoc", "SVAIR", "SVA_CLASSES", "norm_class",
    "load_sva_ir", "validate_sva", "validate_sva_text",
    "build_matrix", "matrix_of", "sva_status", "render_sva_markdown",
]
