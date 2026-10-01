"""真实 case 核对页 —— 拿真实 case 列表反过来量模型。

四个方向：模型落后于实现 / 实现落后于模型 / 重复 / 缺环境指纹。
真实 case 的缺陷**不进模型评分** —— 评分必须只是模型的属性，
否则换一份 case 列表分数就变，不再可复现。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ....analysis import AnalysisResult
from .base import Tab

_HINT = (
    "载入真实 case 列表（.yaml/.yml/.json/.csv），拿它和模型对账：\n"
    "  ① 模型落后于实现？ 真实 case 用了模型没声明的字段 / 取值 / 专题\n"
    "  ② 实现落后于模型？ 模型覆盖了、真实 case 没写\n"
    "  ③ 有重复 case 吗？ 对象+节点+字段取值相同即重复（文档十二节）\n"
    "  ④ 有 case 缺环境指纹吗？ 缺了就不可复现\n"
    "输入格式与 generate --format 的输出同构，所以「生成 → 落盘 → 核对」可闭环。\n"
    "真实 case 的缺陷不计入模型完备性评分。"
)


class ExternalTab(Tab):
    title = "真实 case 核对"
    hint = _HINT

    def build(self) -> None:
        outer = ttk.Frame(self.frame, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        bar = ttk.Frame(outer)
        bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(bar, text="载入真实 case 列表…",
                   command=self.app.on_load_cases).pack(side=tk.LEFT)
        ttk.Button(bar, text="清除", command=self.app.on_clear_cases).pack(
            side=tk.LEFT, padx=(6, 0))
        self.path_label = ttk.Label(bar, text="（未载入）", foreground="#5f6b7a")
        self.path_label.pack(side=tk.LEFT, padx=(12, 0))

        self.hint_label(outer)

        box = ttk.LabelFrame(outer, text="核对结论", padding=6)
        box.pack(fill=tk.X)
        self.summary_view = ttk.Treeview(box, columns=("item", "value"),
                                        show="headings", height=7)
        for col, head, width in (("item", "项", 250), ("value", "结果", 750)):
            self.summary_view.heading(col, text=head)
            self.summary_view.column(col, width=width, anchor=tk.W)
        self.summary_view.pack(fill=tk.X)
        for tag, color in (("bad", "#c62828"), ("warn", "#ef6c00"),
                           ("ok", "#2e7d32")):
            self.summary_view.tag_configure(tag, foreground=color)

        detail = ttk.LabelFrame(outer, text="明细（缺口 / 重复 / 未声明 / 命名）",
                                padding=6)
        detail.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.detail_view = ttk.Treeview(detail, columns=("kind", "where", "what"),
                                        show="headings")
        for col, head, width in (("kind", "类型", 170), ("where", "位置", 230),
                                 ("what", "内容", 660)):
            self.detail_view.heading(col, text=head)
            self.detail_view.column(col, width=width, anchor=tk.W)
        vsb = ttk.Scrollbar(detail, orient=tk.VERTICAL,
                            command=self.detail_view.yview)
        self.detail_view.configure(yscrollcommand=vsb.set)
        self.detail_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)
        self.detail_view.tag_configure("error", foreground="#c62828")
        self.detail_view.tag_configure("warning", foreground="#ef6c00")

    def refresh(self, result: AnalysisResult) -> None:
        ext = result.external
        self.summary_view.delete(*self.summary_view.get_children())
        self.detail_view.delete(*self.detail_view.get_children())
        if ext is None:
            self.path_label.configure(text="（未载入）")
            return

        self.path_label.configure(text=str(self.app.cases_path or ext.source))
        rows = [
            ("真实 case 数", str(ext.case_count), "ok"),
            ("真实取值覆盖", f"{ext.coverage_ratio:.1%}",
             "ok" if ext.coverage_ratio >= 0.99 else "warn"),
            ("模型生成覆盖", f"{ext.generated_ratio:.1%}", "ok"),
            ("实现落后于模型（真实缺口）", f"{len(ext.generated_only)} 个取值",
             "warn" if ext.generated_only else "ok"),
            ("模型落后于实现",
             f"{len(ext.unknown_fields)} 个未声明字段 + "
             f"{len(ext.undeclared_values)} 个未声明取值 + "
             f"{len(ext.unknown_themes)} 个未声明专题",
             "bad" if (ext.unknown_fields or ext.undeclared_values
                       or ext.unknown_themes) else "ok"),
            ("重复 case", f"{len(ext.duplicates)} 组",
             "warn" if ext.duplicates else "ok"),
            ("缺环境指纹 / 缺检查项",
             f"{ext.cases_without_environment} / {ext.cases_without_checks}",
             "bad" if ext.cases_without_environment
             else ("warn" if ext.cases_without_checks else "ok")),
        ]
        for item, value, tag in rows:
            self.summary_view.insert("", tk.END, tags=(tag,), values=(item, value))

        details = []
        for dim, fname, token in ext.generated_only:
            details.append(("真实缺口", f"[{dim}] {fname}", token, "warning"))
        for desc, ids in ext.duplicates:
            details.append(("重复 case", desc, "、".join(ids), "warning"))
        for cid, fname in ext.unknown_fields:
            details.append(("未声明字段", cid, fname, "error"))
        for cid, fname, token in ext.undeclared_values:
            details.append(("未声明取值", cid, f"{fname} = {token}", "error"))
        for cid, theme_id in ext.unknown_themes:
            details.append(("未声明专题", cid, theme_id, "error"))
        for cid, node in ext.unknown_nodes:
            details.append(("未知节点", cid, node, "error"))
        for cid, reason in ext.invalid_ids:
            details.append(("命名不合规", cid, reason, "warning"))
        for kind, where, what, tag in details:
            self.detail_view.insert("", tk.END, tags=(tag,),
                                    values=(kind, where, what))
        if not details:
            self.detail_view.insert("", tk.END, values=("（无）", "", "核对通过"))
