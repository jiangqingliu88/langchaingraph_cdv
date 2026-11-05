"""scb_ir 门面 —— YAML/JSON → IR → 校验 / 矩阵 / Markdown。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..ir_common import load_doc, result
from .ir_core import SCBDoc
from .validate import build_matrix, validate_scb
from .views import render_markdown


def load_scb_ir(text_or_path: str | Path) -> SCBDoc:
    return SCBDoc.from_dict(load_doc(text_or_path))


def validate_scb_text(text_or_path: str | Path) -> Dict[str, Any]:
    try:
        return validate_scb(load_scb_ir(text_or_path))
    except (ValueError, OSError) as exc:
        return result([f"scb_ir 解析失败：{exc}"])


def matrix_of(text_or_path: str | Path) -> Dict[str, Any]:
    try:
        return build_matrix(load_scb_ir(text_or_path))
    except (ValueError, OSError) as exc:
        return {"error": f"scb_ir 解析失败：{exc}", "cells": [], "rows": []}


def render_scb_markdown(text_or_path: str | Path) -> str:
    doc = load_scb_ir(text_or_path)
    return render_markdown(doc, validate_scb(doc))
