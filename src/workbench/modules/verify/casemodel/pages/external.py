"""真实 case 核对 —— 拿真实 case 列表反过来量模型。

四个方向：模型落后于实现 / 实现落后于模型 / 重复 / 缺环境指纹。
真实 case 的缺陷**不进模型评分** —— 评分必须只是模型的属性，
否则换一份 case 列表分数就变，不再可复现。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from src.workbench.ui import theme
from src.workbench.ui.models import RowsModel

from ..page import Page

_HINT = ("载入真实 case 列表（.yaml/.yml/.json/.csv），拿它和模型对账：\n"
         "① 模型落后于实现？真实 case 用了模型没声明的字段 / 取值 / 专题　"
         "② 实现落后于模型？模型覆盖了、真实 case 没写\n"
         "③ 有重复 case 吗？对象+节点+字段取值相同即重复（文档十二节）　"
         "④ 有 case 缺环境指纹吗？缺了就不可复现\n"
         "输入格式与 generate --format 的输出同构，可闭环。"
         "真实 case 的缺陷不计入模型完备性评分。")

SUMMARY_COLUMNS = (
    ("item", "项", 250, "left"),
    ("value", "结果", 700, "left"),
)
DETAIL_COLUMNS = (
    ("kind", "类型", 170, "left"),
    ("where", "位置", 240, "left"),
    ("what", "内容", 620, "left"),
)


class ExternalPage(Page):
    TITLE = "真实 case 核对"
    HINT = _HINT

    def build(self) -> None:
        outer = self.frame()

        bar = QHBoxLayout()
        load = QPushButton("载入真实 case 列表…")
        load.clicked.connect(self.module.on_load_cases)
        bar.addWidget(load)
        clear = QPushButton("清除")
        clear.clicked.connect(self.module.on_clear_cases)
        bar.addWidget(clear)
        bar.addSpacing(10)
        self.path_label = QLabel("（未载入）")
        self.path_label.setStyleSheet(f"color: {theme.MUTED.name()};")
        bar.addWidget(self.path_label, 1)
        outer.addLayout(bar)

        outer.addWidget(self.hint_label())

        splitter = QSplitter(Qt.Orientation.Vertical)
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.addWidget(self.section_label("核对结论"))
        self.summary_model = RowsModel(SUMMARY_COLUMNS, self)
        self.summary_view = self.make_table(self.summary_model)
        box_layout.addWidget(self.summary_view, 1)
        splitter.addWidget(box)

        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(self.section_label("明细　缺口 / 重复 / 未声明 / 命名"))
        self.detail_model = RowsModel(DETAIL_COLUMNS, self)
        self.detail_view = self.make_table(self.detail_model)
        detail_layout.addWidget(self.detail_view, 1)
        splitter.addWidget(detail_box)

        splitter.setSizes([260, 320])
        outer.addWidget(splitter, 1)

    def refresh(self, result) -> None:
        ext = result.external
        if ext is None:
            self.path_label.setText("（未载入）")
            self.summary_model.set_rows([])
            self.detail_model.set_rows([])
            return

        self.path_label.setText(str(self.module.cases_path or ext.source))
        G, W, E = (theme.COVERAGE["full"],
                   theme.SEVERITY["warning"],
                   theme.SEVERITY["error"])
        summary = [
            ("真实 case 数", str(ext.case_count), G),
            ("真实取值覆盖", f"{ext.coverage_ratio:.1%}",
             G if ext.coverage_ratio >= 0.99 else W),
            ("模型生成覆盖", f"{ext.generated_ratio:.1%}", G),
            ("实现落后于模型（真实缺口）", f"{len(ext.generated_only)} 个取值",
             W if ext.generated_only else G),
            ("模型落后于实现",
             f"{len(ext.unknown_fields)} 个未声明字段 + "
             f"{len(ext.undeclared_values)} 个未声明取值 + "
             f"{len(ext.unknown_themes)} 个未声明专题",
             E if (ext.unknown_fields or ext.undeclared_values
                   or ext.unknown_themes) else G),
            ("重复 case", f"{len(ext.duplicates)} 组",
             W if ext.duplicates else G),
            ("缺环境指纹 / 缺检查项",
             f"{ext.cases_without_environment} / {ext.cases_without_checks}",
             E if ext.cases_without_environment
             else (W if ext.cases_without_checks else G)),
        ]
        self.summary_model.set_rows(
            [{"item": i, "value": v} for i, v, _c in summary],
            cell_colors={(i, 1): c for i, (_t, _v, c) in enumerate(summary)})

        details = []
        for dim, field, token in ext.generated_only:
            details.append(("真实缺口", f"[{dim}] {field}", token, W))
        for desc, ids in ext.duplicates:
            details.append(("重复 case", desc, "、".join(ids), W))
        for cid, field in ext.unknown_fields:
            details.append(("未声明字段", cid, field, E))
        for cid, field, token in ext.undeclared_values:
            details.append(("未声明取值", cid, f"{field} = {token}", E))
        for cid, theme_id in ext.unknown_themes:
            details.append(("未声明专题", cid, theme_id, E))
        for cid, node in ext.unknown_nodes:
            details.append(("未知节点", cid, node, E))
        for cid, reason in ext.invalid_ids:
            details.append(("命名不合规", cid, reason, W))
        self.detail_model.set_rows(
            [{"kind": k, "where": w, "what": t} for k, w, t, _c in details],
            row_colors={i: c for i, (_k, _w, _t, c) in enumerate(details)})

    def clear(self) -> None:
        self.summary_model.set_rows([])
        self.detail_model.set_rows([])
        self.path_label.setText("（未载入）")
