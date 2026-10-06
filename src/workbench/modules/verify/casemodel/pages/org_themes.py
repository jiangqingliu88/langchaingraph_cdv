"""功能组织树 / 专题 —— 骨架与横切关注点。

左边是树：缩进表达层级，标出打在这里的专题与 case 数。
右边是专题：优先级、作用目标、维度范围、实际产出。

两张表并排是刻意的：树回答「结构覆盖全了吗」，专题回答「轮次铺开了吗」——
它们是同一个问题的两面（专题作用于树）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QTreeView, QVBoxLayout, QWidget

from src.workbench.ui import theme
from src.workbench.ui.models import RowsModel

from ..models import OrgTreeModel
from ..page import Page

THEME_COLUMNS = (
    ("priority", "优先级", 66, "center"),
    ("id", "专题", 110, "left"),
    ("name", "名称", 180, "left"),
    ("kind_name", "类型", 150, "left"),
    ("target", "作用目标", 220, "left"),
    ("dimensions", "维度", 200, "left"),
    ("method", "方法", 70, "center"),
    ("case_count", "case 数", 80, "center"),
)


class OrgThemesPage(Page):
    TITLE = "组织树 / 专题"
    HINT = ("功能组织树是结构骨架，专题是横切在骨架上的验证关注点（P0/P1/P2 分层）。"
            "专题的 applies_to 指向分支时会自动展开到它的叶子；留空表示不作用树"
            "（错误和异常 / 性能常稳这类全局正交关注点）。")

    def build(self) -> None:
        outer = self.frame()
        outer.addWidget(self.hint_label())

        splitter = QSplitter(Qt.Orientation.Vertical)

        tree_box = QWidget()
        tree_layout = QVBoxLayout(tree_box)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.addWidget(self.section_label("功能组织树　只有叶子生成 case"))
        self.tree_model = OrgTreeModel(self)
        self.tree_view = QTreeView(self)
        self.tree_view.setModel(self.tree_model)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.header().setStretchLastSection(True)
        self.tree_model.apply_column_widths(self.tree_view)
        tree_layout.addWidget(self.tree_view, 1)
        splitter.addWidget(tree_box)

        theme_box = QWidget()
        theme_layout = QVBoxLayout(theme_box)
        theme_layout.setContentsMargins(0, 0, 0, 0)
        theme_layout.addWidget(self.section_label("专题　按优先级排序"))
        self.theme_model = RowsModel(THEME_COLUMNS, self)
        self.theme_view = self.make_table(self.theme_model)
        theme_layout.addWidget(self.theme_view, 1)
        splitter.addWidget(theme_box)

        splitter.setSizes([340, 300])
        outer.addWidget(splitter, 1)

    def refresh(self, result) -> None:
        self.tree_model.set_result(result)
        self.tree_view.expandAll()

        rows = result.theme_rows()
        colors = {}
        for i, row in enumerate(rows):
            if row["kind"] == "orthogonal":
                colors[(i, 3)] = theme.SEVERITY["info"]
            if not row["case_count"]:
                colors[(i, 7)] = theme.SEVERITY["error"]
        self.theme_model.set_rows(rows, cell_colors=colors)

    def clear(self) -> None:
        self.tree_model.set_result(None)
        self.theme_model.set_rows([])
