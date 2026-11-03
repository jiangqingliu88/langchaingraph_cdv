"""Case 关联视图 —— 四层证据的人类可读四张表（用例 / 契约 / 矩阵 / 缺口）。"""
from .api import build_case_view, load_case_view, write_case_view
from .builder import SCHEMA
from .render import render_html, render_markdown, render_terminal, write_reports

__all__ = [
    "SCHEMA", "build_case_view", "load_case_view", "write_case_view",
    "render_html", "render_markdown", "render_terminal", "write_reports",
]
