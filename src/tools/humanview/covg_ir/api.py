"""covg_ir 门面 —— YAML/JSON → IR → 校验 / 矩阵 / Markdown。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..ir_common import load_doc, result
from .ir_core import CovgIR
from .validate import build_matrix, validate_covg
from .views import render_markdown


def load_covg_ir(text_or_path: str | Path) -> CovgIR:
    return CovgIR.from_dict(load_doc(text_or_path))


def validate_covg_text(text_or_path: str | Path) -> Dict[str, Any]:
    try:
        return validate_covg(load_covg_ir(text_or_path))
    except (ValueError, OSError) as exc:
        return result([f"covg_ir 解析失败：{exc}"])


def matrix_of(text_or_path: str | Path) -> Dict[str, Any]:
    try:
        return build_matrix(load_covg_ir(text_or_path))
    except (ValueError, OSError) as exc:
        return {"error": f"covg_ir 解析失败：{exc}", "groups": [], "rows": []}


def render_covg_markdown(text_or_path: str | Path) -> str:
    ir = load_covg_ir(text_or_path)
    return render_markdown(ir, validate_covg(ir))
