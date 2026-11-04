"""Case 关联视图 —— 四层证据的人类可读视图 + Case Gate。

v2 在 v1 四张表（用例 / 契约 / 矩阵 / 缺口）之上追加三张
（分类树 / Case×CELL / 执行证据）与一份元数据（SSOT 指纹 / 只读）。
门禁 `gates` 与视图同包：规则读的是同一批生成物。
"""
from .api import build_case_view, load_case_view, write_case_view
from .builder import SCHEMA
from .gates import (
    load_declarative, load_rules, rules_table, validate_case_view, write_gates,
)
from .render import render_html, render_markdown, render_terminal, write_reports

__all__ = [
    "SCHEMA", "build_case_view", "load_case_view", "write_case_view",
    "load_declarative", "load_rules", "rules_table", "validate_case_view",
    "write_gates",
    "render_html", "render_markdown", "render_terminal", "write_reports",
]
