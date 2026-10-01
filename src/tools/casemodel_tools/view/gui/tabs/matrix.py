"""维度交叉矩阵页 —— 「然后是维度的约束组合」这一层。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ....analysis import AnalysisResult
from ..widgets import LEVEL_FILL, MatrixCanvas
from .base import Tab


class MatrixTab(Tab):
    title = "维度交叉矩阵"
    hint = ("专题选定范围之后，矩阵约束这些维度怎么配：★ 必需 / ✓ 可选 / "
            "✗ 禁止。点任一格子看它的来源与理由。")

    def build(self) -> None:
        outer = ttk.Frame(self.frame, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        legend = ttk.Frame(outer)
        legend.pack(fill=tk.X)
        for text, color in (("★ 必需交叉", LEVEL_FILL["required"]),
                            ("✓ 可选交叉", LEVEL_FILL["optional"]),
                            ("✗ 禁止交叉", LEVEL_FILL["forbidden"]),
                            ("空 未声明", LEVEL_FILL["none"])):
            tk.Label(legend, text="  ", background=color, relief=tk.SOLID,
                     borderwidth=1).pack(side=tk.LEFT, padx=(0, 4))
            ttk.Label(legend, text=text).pack(side=tk.LEFT, padx=(0, 14))

        body = ttk.Frame(outer)
        body.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        holder = ttk.Frame(body)
        holder.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.label = ttk.Label(body, text="", width=36, anchor=tk.NW,
                               justify=tk.LEFT, wraplength=280)
        self.label.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0))

        wrap = ttk.Frame(holder)
        wrap.pack(fill=tk.BOTH, expand=True)
        vsb = ttk.Scrollbar(wrap, orient="vertical")
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas = MatrixCanvas(wrap)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.on_pick = self._on_pick

        groups = ttk.LabelFrame(outer, text="专题规模估算（这一轮会跑出多少 case）",
                                padding=6)
        groups.pack(fill=tk.BOTH, expand=False, pady=(8, 0))
        self.group_view = ttk.Treeview(
            groups, columns=("theme", "name", "priority", "kind", "dims",
                             "method", "targets", "size"), show="headings",
            height=6)
        for col, head, width in (("theme", "专题", 110), ("name", "名称", 190),
                                 ("priority", "优先级", 66),
                                 ("kind", "类型", 150), ("dims", "维度数", 70),
                                 ("method", "方法", 80), ("targets", "目标数", 70),
                                 ("size", "规模", 80)):
            self.group_view.heading(col, text=head)
            self.group_view.column(col, width=width,
                                   anchor=(tk.W if col in ("name", "kind")
                                           else tk.CENTER))
        self.group_view.pack(fill=tk.BOTH, expand=True)
        self.group_view.tag_configure("explosive", foreground="#c62828")

    def _on_pick(self, a: str, b: str, cell) -> None:
        source = ("显式声明" if cell.source == "declared"
                  else "交叉组隐含" if cell.source == "group" else "未声明")
        self.label.configure(
            text=f"{a}  ×  {b}\n\n级别：{cell.mark} {cell.level_name}\n"
                 f"来源：{source}\n"
                 + (f"理由：{cell.reason}\n" if cell.reason else ""))

    def refresh(self, result: AnalysisResult) -> None:
        matrix = result.matrix
        self.canvas.set_matrix(matrix)
        if matrix is not None:
            self.label.configure(
                text=f"{len(matrix.dimensions)} 个维度，{matrix.total_pairs()} 对组合\n"
                     f"已声明 {matrix.declared_count()} 对，"
                     f"未声明 {matrix.undeclared_count()} 对\n\n"
                     f"点击任一格子查看该对的来源与理由。")
        self.group_view.delete(*self.group_view.get_children())
        for exp in result.explosion:
            self.group_view.insert(
                "", tk.END, tags=("explosive",) if exp["explosive"] else (),
                values=(exp["theme"], exp["name"], exp["priority"],
                        exp["kind_name"], len(exp["dimensions"]), exp["method"],
                        exp["targets"], exp["size"]))
