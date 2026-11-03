"""Scoreboard 分解 IR（见同目录 `arch.md`）。"""
from .api import (load_scb_ir, matrix_of, render_scb_markdown,
                  validate_scb_text)
from .ir_core import (SCB_CLASSES, SCB_MODELS, SCBDoc, SCBIR, norm_class,
                      norm_model)
from .validate import build_matrix, scb_status, validate_scb

__all__ = [
    "SCBDoc", "SCBIR", "SCB_CLASSES", "SCB_MODELS", "norm_class", "norm_model",
    "load_scb_ir", "validate_scb", "validate_scb_text",
    "build_matrix", "matrix_of", "scb_status", "render_scb_markdown",
]
