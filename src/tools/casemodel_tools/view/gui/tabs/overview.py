"""概览页 —— 分层结构与评分拆解。

一屏回答两个问题：「这个模型由什么组成」和「它哪里扣分了」。
评分拆解带扣分原因，点得进具体规则 —— 不然一个数字没法行动。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ....analysis import AnalysisResult
from .base import Tab


class OverviewTab(Tab):
    title = "概览"
    hint = ("六层属性结构 + 环境。评分是模型的属性：同一份模型无论传哪份外部 "
            "case 列表，分数都一样 —— 否则不可复现。")

    def build(self) -> None:
        outer = ttk.Frame(self.frame, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(outer)
        top.pack(fill=tk.X)
        self.score_label = ttk.Label(top, text="—",
                                     font=("TkDefaultFont", 30, "bold"),
                                     foreground="#2e7d32")
        self.score_label.pack(side=tk.LEFT, padx=(4, 16))
        self.summary_label = ttk.Label(top, text="", justify=tk.LEFT)
        self.summary_label.pack(side=tk.LEFT, padx=(12, 0))

        panes = ttk.Frame(outer)
        panes.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        left = ttk.LabelFrame(panes, text="分层结构（L1 → L6 + 专题 + 环境）",
                              padding=6)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.layer_tree = ttk.Treeview(
            left, columns=("layer", "name", "role", "count", "detail"),
            show="headings")
        for col, head, width in (("layer", "层", 46), ("name", "名称", 190),
                                 ("role", "作用", 150), ("count", "数量", 54),
                                 ("detail", "明细", 520)):
            self.layer_tree.heading(col, text=head)
            self.layer_tree.column(col, width=width,
                                   stretch=(col == "detail"), anchor=tk.W)
        self.layer_tree.pack(fill=tk.BOTH, expand=True)

        right = ttk.LabelFrame(panes, text="评分拆解（子分 × 权重 = 加权得分）",
                               padding=6)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))
        self.score_tree = ttk.Treeview(
            right, columns=("item", "sub", "weighted", "reason"),
            show="headings")
        for col, head, width in (("item", "评分项", 110), ("sub", "子分", 60),
                                 ("weighted", "加权", 60),
                                 ("reason", "扣分原因", 460)):
            self.score_tree.heading(col, text=head)
            self.score_tree.column(col, width=width,
                                   anchor=(tk.W if col == "reason" else tk.CENTER))
        self.score_tree.pack(fill=tk.BOTH, expand=True)
        for tag, color in (("ok", "#2e7d32"), ("mid", "#ef6c00"), ("low", "#c62828")):
            self.score_tree.tag_configure(tag, foreground=color)

    def refresh(self, result: AnalysisResult) -> None:
        score = result.score.total
        self.score_label.configure(
            text=f"{score:.0f}",
            foreground=("#2e7d32" if score >= 85 else
                        "#ef6c00" if score >= 60 else "#c62828"))
        s = result.summary()
        gen = result.generation
        lines = [
            f"{result.model.object_label}    版本 {result.model.version or '—'}",
            f"组织树 {s['org_leaf_count']} 个叶子    专题 {s['theme_count']} 个"
            f"（{'、'.join(gen.priorities_used) or '—'}）    "
            f"驱动 {gen.driver}",
            f"case {s['case_count']} 个"
            + (f"（组合规模 {s['case_total_before_cap']}，截断丢弃 {s['dropped']}）"
               if s["truncated"] else "")
            + f"    seed {gen.seed}",
            f"取值覆盖 {result.coverage_ratio:.1%}    "
            f"错误 {s['error_count']} / 警告 {s['warning_count']} / 提示 {s['info_count']}",
        ]
        self.summary_label.configure(text="\n".join(lines))

        self.layer_tree.delete(*self.layer_tree.get_children())
        for row in result.model.layer_rows():
            self.layer_tree.insert("", tk.END, values=(
                row["layer"], row["name"], row["role"], row["count"],
                row["detail"]))

        self.score_tree.delete(*self.score_tree.get_children())
        for name, sub, weighted, reasons in result.score.row_reasons():
            tag = "ok" if sub >= 0.85 else "mid" if sub >= 0.5 else "low"
            self.score_tree.insert("", tk.END, tags=(tag,), values=(
                name, f"{sub:.2f}", f"{weighted:.1f}",
                "；".join(reasons) or "—"))
