"""维度交叉矩阵 —— 「然后是维度的约束组合」这一层。

正交属性怎么 cross 就是这一页在回答的问题：专题先选范围，矩阵再约束这些
维度哪些必须一起变、哪些可选、哪些互斥。下面那张表估这一轮会跑出多少 case。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel

from src.workbench.ui import theme
from src.workbench.ui.views.matrix import MatrixView
from src.workbench.ui.models import RowsModel

from ..page import Page

ESTIMATE_COLUMNS = (
    ("theme", "专题", 110, "left"),
    ("name", "名称", 190, "left"),
    ("priority", "优先级", 66, "center"),
    ("kind_name", "类型", 150, "left"),
    ("dimensions", "维度", 220, "left"),
    ("method", "方法", 80, "center"),
    ("targets", "目标数", 70, "center"),
    ("size", "规模", 80, "center"),
)


class MatrixPage(Page):
    TITLE = "维度交叉矩阵"
    HINT = ("专题选定范围之后，矩阵约束这些维度怎么配：★ 必需 / ✓ 可选 / ✗ 禁止。"
            "点格子或悬停看它的来源与理由；下面那张表是「这一轮会跑出多少 case」的估算。")

    def build(self) -> None:
        outer = self.frame()

        top = QHBoxLayout()
        top.addWidget(self.hint_label(), 1)
        self.detail = QLabel("")
        self.detail.setMinimumWidth(300)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(f"color: {theme.MUTED.name()};")
        top.addWidget(self.detail)
        outer.addLayout(top)

        self.matrix_view = MatrixView(self)
        self.matrix_view.cellPicked.connect(self._on_cell)
        outer.addWidget(self.matrix_view, 2)

        outer.addWidget(self.section_label("专题规模估算　用 G 方法会不会炸"))
        self.model = RowsModel(ESTIMATE_COLUMNS, self)
        self.view = self.make_table(self.model)
        self.view.setMaximumHeight(200)
        outer.addWidget(self.view, 1)

    def _on_cell(self, a: str, b: str, cell) -> None:
        source = ("显式声明" if cell.source == "declared"
                  else "交叉组隐含" if cell.source == "group" else "未声明")
        reason = f"\n理由：{cell.reason}" if cell.reason else ""
        self.detail.setText(f"{a} × {b}\n级别：{cell.mark} {cell.level_name}"
                            f"\n来源：{source}{reason}")

    def refresh(self, result) -> None:
        matrix = result.matrix
        self.matrix_view.set_matrix(matrix)
        if matrix is not None:
            self.detail.setText(
                f"{len(matrix.dimensions)} 个维度，{matrix.total_pairs()} 对组合\n"
                f"已声明 {matrix.declared_count()} 对，"
                f"未声明 {matrix.undeclared_count()} 对\n\n"
                f"点任一格子查看该对的来源与理由。")
        # 维度是 list，直接塞进表格会显示成 Python 列表的 repr —— 展平成顿号
        rows = [dict(row, dimensions="、".join(row.get("dimensions") or []))
                for row in result.explosion]
        colors = {i: theme.SEVERITY["error"]
                  for i, row in enumerate(rows) if row["explosive"]}
        self.model.set_rows(rows, row_colors=colors)

    def clear(self) -> None:
        self.matrix_view.set_matrix(None)
        self.model.set_rows([])
        self.detail.clear()
