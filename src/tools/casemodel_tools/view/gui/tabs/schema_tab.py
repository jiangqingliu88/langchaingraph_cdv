"""Schema 校验页 —— 原始 YAML 的语法/类型/必填/形状。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ....analysis import AnalysisResult
from ..widgets import IssueTable
from .base import Tab


class SchemaTab(Tab):
    title = "Schema 校验"
    hint = ("用 schema/case_model.schema.json 校验原始 YAML。schema 只回答"
            "「文档写对了吗」；引用是否存在、层级是否错位由其它标签页回答。")

    def build(self) -> None:
        outer = ttk.Frame(self.frame, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)
        self.hint = self.hint_label(outer)
        self.table = IssueTable(
            outer, empty_hint="schema 校验通过（语法 / 类型 / 必填 / 类型化取值表形状）。")
        self.table.pack(fill=tk.BOTH, expand=True)

    def refresh(self, result: AnalysisResult) -> None:
        issues = self.app.schema_issues
        self.table.set_issues(issues)
        self.hint.configure(text=f"{self.hint.cget('text').split('文件：')[0]}"
                                 f"文件：{self.app.path}")
