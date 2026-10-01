"""GUI 可复用控件。

放在表现层的公共位置，因为它们被多个标签页共用：
  IssueTable    诊断表（严重度着色）—— 正交性 / 环境 / schema / 外部 四处都用
  MatrixCanvas  维度交叉矩阵画布
  TreeTable     带缩进的树表 —— 功能组织树用
  bar_text      文本覆盖条 —— 与 CLI 的观感保持一致

控件不含判定逻辑：它们只接收已经算好的数据并显示。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional, Sequence, Tuple

from ...analysis import Issue, count_by_severity

# ── 配色 ──
BG = "#f7f8fa"
FG = "#1f2329"
SEVERITY_COLORS = {"error": "#c62828", "warning": "#ef6c00", "info": "#1565c0"}
LEVEL_FILL = {"required": "#ffcdd2", "optional": "#fff3c4",
              "forbidden": "#e0e0e0", "none": "#ffffff"}
BAR_GOOD, BAR_WARN, BAR_BAD = "#43a047", "#fb8c00", "#e53935"

CJK_FONTS = ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "PingFang SC",
             "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Source Han Sans SC")


def pick_font(root: "tk.Misc") -> Optional[str]:
    """挑一个能显示中文的字体 —— 挑不到就交给 Tk 默认。"""
    from tkinter import font as tkfont
    families = set(tkfont.families(root))
    return next((f for f in CJK_FONTS if f in families), None)


def short(text: str, width: int = 6) -> str:
    text = text or ""
    return text if len(text) <= width else text[: width - 1] + "…"


def bar_text(ratio: float, width: int = 10) -> str:
    filled = int(round(max(0.0, min(1.0, ratio)) * width))
    return "█" * filled + "░" * (width - filled)


def ratio_color(ratio: float) -> str:
    return (BAR_GOOD if ratio >= 0.999 else
            BAR_WARN if ratio >= 0.5 else BAR_BAD)


# ════════════════════════════════════════════════════════════
# 诊断表
# ════════════════════════════════════════════════════════════

class IssueTable(ttk.Frame):
    """诊断条目表：严重度 / 分类 / 规则 / 目标 / 说明。"""

    COLUMNS = ("severity", "category", "rule", "target", "message")
    HEADINGS = ("严重度", "分类", "规则", "目标", "说明")
    WIDTHS = (70, 110, 200, 250, 620)

    def __init__(self, master: "tk.Misc", empty_hint: str = "（无）") -> None:
        super().__init__(master)
        self.empty_hint = empty_hint
        self.tree = ttk.Treeview(self, columns=self.COLUMNS, show="headings")
        for col, head, width in zip(self.COLUMNS, self.HEADINGS, self.WIDTHS):
            self.tree.heading(col, text=head)
            self.tree.column(col, width=width, stretch=(col == "message"),
                             anchor=tk.W)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        for sev, color in SEVERITY_COLORS.items():
            self.tree.tag_configure(sev, foreground=color)
        self.summary = ttk.Label(self, text="", anchor=tk.W)
        self.summary.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def set_issues(self, issues: Sequence[Issue], hint: str = "") -> None:
        self.tree.delete(*self.tree.get_children())
        for issue in issues:
            self.tree.insert("", tk.END, tags=(issue.severity,),
                             values=(issue.severity_cn, issue.category_cn,
                                     issue.rule, issue.target, issue.message))
        if not issues:
            self.summary.configure(text=hint or self.empty_hint)
            return
        c = count_by_severity(issues)
        self.summary.configure(
            text=f"共 {len(issues)} 条 —— 错误 {c['error']}  警告 {c['warning']}  "
                 f"提示 {c['info']}" + (f"    {hint}" if hint else ""))


# ════════════════════════════════════════════════════════════
# 交叉矩阵
# ════════════════════════════════════════════════════════════

class MatrixCanvas(tk.Canvas):
    """维度交叉矩阵 —— ★ 必需 / ✓ 可选 / ✗ 禁止 / 空 未声明。"""

    HEADER = 118

    def __init__(self, master: "tk.Misc") -> None:
        super().__init__(master, background="white", highlightthickness=1,
                         highlightbackground="#d0d5dd")
        self.matrix = None
        self.on_pick = None
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_matrix(self, matrix) -> None:
        self.matrix = matrix
        self.redraw()

    def _cell_size(self, n: int) -> int:
        if n <= 0:
            return 60
        avail = max(self.winfo_width(), 560) - self.HEADER - 24
        return max(26, min(66, avail // max(1, n)))

    def redraw(self) -> None:
        self.delete("all")
        matrix = self.matrix
        if matrix is None or not matrix.dimensions:
            self.create_text(16, 16, anchor=tk.NW, fill="#888",
                             text="没有可展示的维度")
            return
        dims = matrix.dimensions
        n = len(dims)
        cell = self._cell_size(n)
        grid = matrix.mark_grid()
        top = 34 + cell
        for j, dim in enumerate(dims):
            self.create_text(self.HEADER + j * cell + cell / 2, top - cell / 2 - 6,
                             text=short(dim.label, 5), fill=FG, justify=tk.CENTER)
        for i, dim in enumerate(dims):
            y = top + i * cell + cell / 2
            self.create_text(self.HEADER - 8, y, anchor=tk.E, fill=FG,
                             text=short(dim.label, 9))
            for j in range(n):
                x0, y0 = self.HEADER + j * cell, top + i * cell
                mark = grid[i][j]
                if i == j:
                    level = "diagonal"
                else:
                    cell_obj = matrix.cells.get((min(i, j), max(i, j)))
                    level = cell_obj.level if cell_obj else "none"
                fill = "#eceff1" if level == "diagonal" else LEVEL_FILL.get(level, "#fff")
                self.create_rectangle(x0, y0, x0 + cell, y0 + cell,
                                      fill=fill, outline="#cfd8dc")
                if mark:
                    self.create_text(x0 + cell / 2, y0 + cell / 2, text=mark,
                                     fill="#37474f",
                                     font=("TkDefaultFont", 11, "bold"))
        self.configure(scrollregion=self.bbox("all"))

    def _click(self, event) -> None:
        matrix = self.matrix
        if matrix is None or not matrix.dimensions or self.on_pick is None:
            return
        n = len(matrix.dimensions)
        cell = self._cell_size(n)
        top = 34 + cell
        if event.x < self.HEADER or event.y < top:
            return
        i = int((event.y - top) // cell)
        j = int((event.x - self.HEADER) // cell)
        if not (0 <= i < n and 0 <= j < n) or i == j:
            return
        c = matrix.cells.get((min(i, j), max(i, j)))
        if c is not None:
            self.on_pick(matrix.dimensions[i].label, matrix.dimensions[j].label, c)


# ════════════════════════════════════════════════════════════
# 树表
# ════════════════════════════════════════════════════════════

class TreeTable(ttk.Frame):
    """带缩进的树表 —— 功能组织树。

    用 Treeview 但靠 `indent` 前缀表达层级：这样每列都能排序/复制，
    比 tkinter 原生的树形展开更适合「一眼看全 + 对齐看数字」的场景。
    """

    def __init__(self, master: "tk.Misc",
                 columns: Sequence[Tuple[str, str, int]],
                 tag_colors: Optional[Dict[str, str]] = None) -> None:
        super().__init__(master)
        keys = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=keys, show="headings")
        for key, head, width in columns:
            self.tree.heading(key, text=head)
            self.tree.column(key, width=width,
                             anchor=(tk.W if key in ("name", "detail", "path",
                                                     "item", "value") else tk.CENTER))
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        for tag, color in (tag_colors or {}).items():
            self.tree.tag_configure(tag, foreground=color)

    def set_rows(self, rows: Sequence[Sequence[object]],
                 tags: Optional[Sequence[str]] = None) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(rows):
            tag = tags[i] if tags and i < len(tags) else ""
            self.tree.insert("", tk.END, tags=(tag,) if tag else (),
                             values=tuple(row))
