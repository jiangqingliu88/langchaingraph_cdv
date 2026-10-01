"""功能组织树 / 专题 —— 骨架与横切关注点。

左表是树：每行一个节点，缩进表达层级，标出打在这里的专题与 case 数。
右表是专题：优先级、作用目标、维度范围、实际产出 —— 一眼看出哪一轮打了哪里。

两张表并排是刻意的：树回答「结构覆盖全了吗」，专题回答「轮次铺开了吗」，
它们是同一个问题的两面（专题作用于树）。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ....analysis import AnalysisResult
from ..widgets import short
from .base import Tab


class OrgThemesTab(Tab):
    title = "组织树 / 专题"
    hint = ("功能组织树是结构骨架，专题是横切在骨架上的验证关注点（P0/P1/P2 分层）。"
            "专题的 applies_to 指向分支时会自动展开到它的叶子。")

    def build(self) -> None:
        outer = ttk.Frame(self.frame, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)
        self.hint_label(outer)

        panes = ttk.Panedwindow(outer, orient=tk.VERTICAL)
        panes.pack(fill=tk.BOTH, expand=True)

        tree_frame = ttk.LabelFrame(panes, text="功能组织树", padding=6)
        self.tree_view = ttk.Treeview(
            tree_frame,
            columns=("node", "code", "themes", "cases", "mark"), show="headings")
        for col, head, width in (("node", "节点（缩进表示层级）", 400),
                                 ("code", "代号", 80),
                                 ("themes", "打在这里的专题", 420),
                                 ("cases", "case 数", 80),
                                 ("mark", "覆盖", 70)):
            self.tree_view.heading(col, text=head)
            self.tree_view.column(col, width=width,
                                  anchor=(tk.W if col in ("node", "themes")
                                          else tk.CENTER))
        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self.tree_view.yview)
        self.tree_view.configure(yscrollcommand=vsb.set)
        self.tree_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree_view.tag_configure("uncovered", foreground="#c62828")
        self.tree_view.tag_configure("branch", foreground="#5f6b7a")
        panes.add(tree_frame, weight=1)

        theme_frame = ttk.LabelFrame(panes, text="专题", padding=6)
        self.theme_view = ttk.Treeview(
            theme_frame,
            columns=("priority", "id", "name", "kind", "target", "dims",
                     "method", "cases"), show="headings")
        for col, head, width in (("priority", "优先级", 66), ("id", "专题", 110),
                                 ("name", "名称", 180), ("kind", "类型", 150),
                                 ("target", "作用目标", 220),
                                 ("dims", "维度", 200), ("method", "方法", 70),
                                 ("cases", "case 数", 80)):
            self.theme_view.heading(col, text=head)
            self.theme_view.column(col, width=width,
                                   anchor=(tk.W if col in ("name", "kind", "target",
                                                           "dims") else tk.CENTER))
        t_vsb = ttk.Scrollbar(theme_frame, orient="vertical",
                              command=self.theme_view.yview)
        self.theme_view.configure(yscrollcommand=t_vsb.set)
        self.theme_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        t_vsb.pack(side=tk.LEFT, fill=tk.Y)
        self.theme_view.tag_configure("orthogonal", foreground="#1565c0")
        panes.add(theme_frame, weight=1)

    def refresh(self, result: AnalysisResult) -> None:
        self.tree_view.delete(*self.tree_view.get_children())
        for row in result.node_rows():
            themes = "、".join(row["themes"]) or (
                "分支（case 由下层叶子承担）" if not row["is_leaf"] else "无")
            mark = ("✓" if row["covered"] and row["is_leaf"]
                    else "·" if not row["is_leaf"] else "✗")
            tag = ("branch" if not row["is_leaf"]
                   else "" if row["covered"] else "uncovered")
            self.tree_view.insert("", tk.END, tags=(tag,) if tag else (),
                                  values=(row["indent"] + row["name"], row["code"],
                                          themes, row["case_count"], mark))

        self.theme_view.delete(*self.theme_view.get_children())
        for row in result.theme_rows():
            tag = "orthogonal" if row["kind"] == "orthogonal" else ""
            self.theme_view.insert(
                "", tk.END, tags=(tag,) if tag else (),
                values=(row["priority"], row["id"], short(row["name"], 16),
                        row["kind_name"], short(row["target"], 24),
                        short(row["dimensions"], 22),
                        row["method"], row["case_count"]))
