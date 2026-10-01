"""Case 属性表页 —— 文档十六节，那张表才是 case 的真正主体。

按生成顺序展示；选中一行在右侧看完整属性（含环境指纹与覆盖仓）。
命名是人读的坐标，属性表才是机器可检索的坐标。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ....analysis import AnalysisResult
from .base import Tab

_BASE_HINT = ("按属性组合生成，case_id 形如 TC-<对象>-<节点>-<方法>-<NN>。"
              "命名是人读的坐标，属性表才是机器可检索的坐标。")


class CasesTab(Tab):
    title = "Case 属性表"
    hint = _BASE_HINT

    def build(self) -> None:
        outer = ttk.Frame(self.frame, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)
        self.hint = self.hint_label(outer)

        pane = ttk.Panedwindow(outer, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)

        frame = ttk.Frame(pane)
        self.view = ttk.Treeview(
            frame, columns=("id", "priority", "theme", "node", "method",
                            "fields", "checks"), show="headings")
        for col, head, width in (("id", "case_id", 180), ("priority", "优先级", 66),
                                 ("theme", "专题", 110), ("node", "节点路径", 200),
                                 ("method", "方法", 60), ("fields", "字段取值", 460),
                                 ("checks", "检查", 180)):
            self.view.heading(col, text=head)
            self.view.column(col, width=width,
                             anchor=(tk.W if col in ("theme", "node", "fields",
                                                     "checks") else tk.CENTER))
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.view.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.view.xview)
        self.view.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.view.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        pane.add(frame, weight=3)

        detail = ttk.LabelFrame(pane, text="case 属性（文档十六节最小字段集）",
                                padding=6)
        self.text = tk.Text(detail, width=46, wrap=tk.WORD, background="#fbfcfd",
                            relief=tk.FLAT)
        d_vsb = ttk.Scrollbar(detail, orient=tk.VERTICAL, command=self.text.yview)
        self.text.configure(yscrollcommand=d_vsb.set)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        d_vsb.pack(side=tk.LEFT, fill=tk.Y)
        pane.add(detail, weight=2)

        self.view.bind("<<TreeviewSelect>>", self._on_select)
        self._by_item = {}

    def _on_select(self, _event=None) -> None:
        sel = self.view.selection()
        if not sel:
            return
        case = self._by_item.get(sel[0])
        if case is None:
            return
        lines = [
            f"case_id        : {case.case_id}",
            f"对象 L1        : {case.object}",
            f"专题           : {case.theme or '（无）'}   "
            f"优先级 {case.priority or '—'}",
            f"树路径 L2      : {case.tree_path or '（不作用功能组织树）'}",
            f"交叉组         : {case.cross_group or '（无）'}",
            "",
            "维度 L3        :",
        ]
        lines += [f"  - {d}" for d in case.dimensions] or ["  - （无）"]
        lines += ["", "字段 L4        :"]
        lines += [f"  {k:<14} = {v}" for k, v in case.fields.items()] or ["  （无）"]
        lines += ["", f"方法 L5        : {case.method} {case.method_name}",
                  "检查 L6        :"]
        lines += [f"  - {c}" for c in case.check_labels()] or ["  - （无）"]
        lines += ["", "覆盖仓         :"]
        lines += [f"  - {b}" for b in case.cover_bins] or ["  - （未映射）"]
        lines += ["", "环境指纹       :"]
        lines += ([f"  {k:<18} = {v}" for k, v in case.environment.items()]
                  or ["  （无）"])
        lines += ["", f"期望结果       : {case.expected_result or '（未声明）'}",
                  f"seed           : {case.seed}"]
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", "\n".join(lines))

    def refresh(self, result: AnalysisResult) -> None:
        gen = result.generation
        self.view.delete(*self.view.get_children())
        self._by_item.clear()
        for case in gen.cases:
            item = self.view.insert("", tk.END, values=(
                case.case_id, case.priority, case.theme,
                case.tree_path or "（不作用树）", case.method,
                "；".join(f"{k}={v}" for k, v in case.fields.items()),
                "、".join(case.checks)))
            self._by_item[item] = case
        tail = f"seed={gen.seed}（同 seed 结果一致）；驱动 {gen.driver}，共 {gen.count} 个"
        if gen.truncated:
            tail += (f"；组合规模 {gen.total_before_cap} 超过上限，"
                     f"已截断丢弃 {gen.dropped} 个")
        self.hint.configure(text=f"{_BASE_HINT}   {tail}")
