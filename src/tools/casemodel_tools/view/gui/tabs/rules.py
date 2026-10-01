"""规则清单页 —— 从规格注册表读，永远不会与实现漂移。

新增一条规则只需在 analysis/rules/ 下写一个 Rule 子类，这一页自动多一行。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ....analysis import AnalysisResult, rule_docs
from ....analysis.issues import CATEGORY_NAMES
from .base import Tab


class RulesTab(Tab):
    title = "规则清单"
    hint = ("全部校验规则，按分类列出。规则由 analysis/rules/ 下的 Rule 子类"
            "自动登记 —— 这一页读的是注册表，不是手写的清单。")

    def build(self) -> None:
        outer = ttk.Frame(self.frame, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)
        self.hint_label(outer)
        self.view = ttk.Treeview(
            outer, columns=("category", "rule", "severity", "description"),
            show="headings")
        for col, head, width in (("category", "分类", 140), ("rule", "规则", 300),
                                 ("severity", "严重度", 80),
                                 ("description", "说明", 620)):
            self.view.heading(col, text=head)
            self.view.column(col, width=width,
                             anchor=(tk.W if col in ("rule", "description")
                                     else tk.CENTER))
        vsb = ttk.Scrollbar(outer, orient="vertical", command=self.view.yview)
        self.view.configure(yscrollcommand=vsb.set)
        self.view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)
        for sev, color in (("error", "#c62828"), ("warning", "#ef6c00"),
                           ("info", "#1565c0")):
            self.view.tag_configure(sev, foreground=color)

    def refresh(self, result: AnalysisResult) -> None:
        self.view.delete(*self.view.get_children())
        for rid, severity, category, desc in rule_docs():
            self.view.insert("", tk.END, tags=(severity,),
                             values=(CATEGORY_NAMES.get(category, category),
                                     rid, severity, desc))
