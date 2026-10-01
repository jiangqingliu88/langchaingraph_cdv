"""环境与检查页 —— 文档九、十节：最容易被遗漏的两层。

环境指纹决定失败 case 能不能复现；检查项决定 case 跑过之后验证了什么。
两者都不是「主体」，所以最容易被漏 —— 这一页专门给它们一个位置。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ....analysis import (AnalysisResult, CATEGORY_ENVIRONMENT,
                          CATEGORY_REFERENCE)
from ....domain import ENV_KEY_NAMES
from ..widgets import IssueTable
from .base import Tab


class EnvironmentTab(Tab):
    title = "环境与检查"
    hint = ("环境指纹：case 不以它为主体，但执行时必须带上，失败才可复现。"
            "检查项：一个 case 往往不止一种检查（功能 / 白盒 / 性能）。")

    def build(self) -> None:
        outer = ttk.Frame(self.frame, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)
        self.hint_label(outer)

        panes = ttk.Frame(outer)
        panes.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(panes, text="环境指纹", padding=6)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.env_view = ttk.Treeview(
            left, columns=("key", "cn", "required", "value", "missing"),
            show="headings")
        for col, head, width in (("key", "环境键", 160), ("cn", "含义", 100),
                                 ("required", "必需", 56),
                                 ("value", "缺省值", 260),
                                 ("missing", "缺失 case", 90)):
            self.env_view.heading(col, text=head)
            self.env_view.column(col, width=width,
                                 anchor=(tk.W if col == "value" else tk.CENTER))
        self.env_view.pack(fill=tk.BOTH, expand=True)
        self.env_view.tag_configure("missing", foreground="#c62828")
        self.env_view.tag_configure("optional", foreground="#5f6b7a")

        right = ttk.LabelFrame(panes, text="检查项（L6）", padding=6)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))
        self.check_view = ttk.Treeview(
            right, columns=("id", "cn", "used"), show="headings")
        for col, head, width in (("id", "检查项", 160), ("cn", "含义", 140),
                                 ("used", "挂载 case 数", 110)):
            self.check_view.heading(col, text=head)
            self.check_view.column(col, width=width,
                                   anchor=(tk.W if col == "cn" else tk.CENTER))
        self.check_view.pack(fill=tk.BOTH, expand=True)
        self.check_view.tag_configure("unused", foreground="#ef6c00")

        self.table = IssueTable(outer, empty_hint="环境指纹与检查项都齐备。")
        self.table.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

    def refresh(self, result: AnalysisResult) -> None:
        model = result.model
        usage = {}
        for case in result.generation.cases:
            for cid in case.checks:
                usage[cid] = usage.get(cid, 0) + 1

        self.env_view.delete(*self.env_view.get_children())
        keys = list(dict.fromkeys(list(model.env_required)
                                 + list(model.case_defaults.environment)))
        for key in keys:
            missing = sum(1 for c in result.generation.cases
                          if key not in c.environment
                          or c.environment.get(key) in (None, ""))
            self.env_view.insert(
                "", tk.END, tags=("missing",) if missing else ("optional",),
                values=(key, ENV_KEY_NAMES.get(key, ""),
                        "是" if key in model.env_required else "否",
                        str(model.case_defaults.environment.get(key, "（无缺省值）")),
                        missing))

        self.check_view.delete(*self.check_view.get_children())
        for cid in model.checks:
            used = usage.get(cid, 0)
            self.check_view.insert("", tk.END, tags=() if used else ("unused",),
                                   values=(cid, model.check_names.get(cid, ""), used))

        by_cat = result.by_category()
        self.table.set_issues(by_cat.get(CATEGORY_ENVIRONMENT, [])
                              + by_cat.get(CATEGORY_REFERENCE, []))
