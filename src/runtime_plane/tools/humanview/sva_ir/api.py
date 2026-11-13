"""sva_ir 门面 —— YAML/JSON → IR → 校验 / 矩阵 / Markdown。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..ir_common import load_doc, result
from .ir_core import SVADoc
from .validate import build_matrix, validate_sva
from .views import render_markdown


def load_sva_ir(text_or_path: str | Path) -> SVADoc:
    return SVADoc.from_dict(load_doc(text_or_path))


def validate_sva_text(text_or_path: str | Path) -> Dict[str, Any]:
    try:
        return validate_sva(load_sva_ir(text_or_path))
    except (ValueError, OSError) as exc:
        return result([f"sva_ir 解析失败：{exc}"])


def matrix_of(text_or_path: str | Path) -> Dict[str, Any]:
    try:
        return build_matrix(load_sva_ir(text_or_path))
    except (ValueError, OSError) as exc:
        return {"error": f"sva_ir 解析失败：{exc}", "cells": [], "rows": []}


def render_sva_markdown(text_or_path: str | Path) -> str:
    doc = load_sva_ir(text_or_path)
    return render_markdown(doc, validate_sva(doc))
