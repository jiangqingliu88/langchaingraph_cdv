"""层级正交性页 —— 文档十八、十九节的四类错位。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ....analysis import AnalysisResult, CATEGORY_ORTHOGONAL
from ..widgets import IssueTable
from .base import Tab


class OrthogonalityTab(Tab):
    title = "层级正交性"
    hint = ("判据只有一条：同一个信息只能存在于一个层级。抓四类错位 —— "
            "把字段当维度 / 把维度当对象 / 把方法当维度 / 把检查当对象。")

    def build(self) -> None:
        outer = ttk.Frame(self.frame, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)
        self.hint_label(outer)
        self.table = IssueTable(outer, empty_hint="没有发现层级错位。")
        self.table.pack(fill=tk.BOTH, expand=True)

    def refresh(self, result: AnalysisResult) -> None:
        self.table.set_issues(result.by_category().get(CATEGORY_ORTHOGONAL, []))
