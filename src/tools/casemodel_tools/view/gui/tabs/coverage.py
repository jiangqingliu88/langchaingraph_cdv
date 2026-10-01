"""取值覆盖页 —— 文档十二节：各字段取值命中数 / 总取值。

左表逐字段给命中率与未命中取值，右侧画布按维度画覆盖条。
联动派生字段标灰：它的取值跟随被联动字段，不是独立的缺口。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ....analysis import AnalysisResult
from ..widgets import bar_text, ratio_color
from .base import Tab


class CoverageTab(Tab):
    title = "取值覆盖"
    hint = ("分母是字段声明的取值点，分子是被 case 命中的。"
            "覆盖为 0 的维度通常意味着它没有被任何专题选中。")

    def build(self) -> None:
        outer = ttk.Frame(self.frame, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)
        self.hint_label(outer)

        panes = ttk.Frame(outer)
        panes.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(panes)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.view = ttk.Treeview(
            left, columns=("dim", "field", "type", "bar", "hit", "missing"),
            show="headings")
        for col, head, width in (("dim", "维度", 150), ("field", "字段", 150),
                                 ("type", "类型", 70), ("bar", "覆盖", 120),
                                 ("hit", "命中/总数", 90),
                                 ("missing", "未命中取值", 340)):
            self.view.heading(col, text=head)
            self.view.column(col, width=width,
                             anchor=(tk.W if col == "missing" else tk.CENTER))
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.view.yview)
        self.view.configure(yscrollcommand=vsb.set)
        self.view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)
        for tag, color in (("full", "#2e7d32"), ("part", "#ef6c00"),
                           ("none", "#c62828"), ("derived", "#5f6b7a")):
            self.view.tag_configure(tag, foreground=color)

        right = ttk.LabelFrame(panes, text="维度覆盖率", padding=6)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))
        self.canvas = tk.Canvas(right, background="white", width=520,
                                highlightthickness=1,
                                highlightbackground="#d0d5dd")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw())

    def refresh(self, result: AnalysisResult) -> None:
        self._result = result
        self.view.delete(*self.view.get_children())
        for dim_cov in result.dimension_coverage:
            for f in dim_cov.fields:
                if f.derived:
                    tag = "derived"
                elif f.ratio >= 0.999:
                    tag = "full"
                elif f.ratio > 0:
                    tag = "part"
                else:
                    tag = "none"
                suffix = "  (联动派生)" if f.derived else ""
                self.view.insert("", tk.END, tags=(tag,), values=(
                    dim_cov.name, f.field, f.type_name,
                    f"{bar_text(f.ratio)} {f.ratio:.0%}",
                    f"{f.hit_count}/{f.total}",
                    ("、".join(f.missing) or "—") + suffix))
        self._draw()

    def _draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        result = getattr(self, "_result", None)
        if result is None:
            return
        dims = result.dimension_coverage
        if not dims:
            canvas.create_text(12, 12, anchor=tk.NW, fill="#888", text="没有维度")
            return
        width = max(canvas.winfo_width(), 320)
        row_h = 24
        limit = max(1, int((max(canvas.winfo_height(), 120) - 20) // row_h))
        label_w, bar_w = 130, max(60, width - 230)
        for idx, d in enumerate(dims[:limit]):
            y = 14 + idx * row_h
            canvas.create_text(8, y + 7, anchor=tk.W, fill="#1f2329", text=d.name)
            canvas.create_rectangle(label_w, y, label_w + bar_w, y + 14,
                                    fill="#eceff1", outline="")
            canvas.create_rectangle(label_w, y,
                                    label_w + max(1, bar_w * d.ratio), y + 14,
                                    fill=ratio_color(d.ratio), outline="")
            canvas.create_text(label_w + bar_w + 8, y + 7, anchor=tk.W,
                               fill="#5f6b7a",
                               text=f"{d.hit_count}/{d.total}")
        if len(dims) > limit:
            canvas.create_text(8, 14 + limit * row_h + 6, anchor=tk.W, fill="#888",
                               text=f"…还有 {len(dims) - limit} 个维度未显示")
