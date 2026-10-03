"""取值覆盖 —— 文档十二节：各字段取值命中数 / 总取值。

覆盖率怎么收敛就是这一页在回答的问题：哪个维度还有取值没被任何 case 命中，
以及那些缺口是不是「联动派生」（跟随被联动字段，不是真缺口）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QSplitter

from src.workbench.ui import theme
from src.workbench.ui.coverage_view import CoverageView
from src.workbench.ui.models import RowsModel

from ..page import Page

FIELD_COLUMNS = (
    ("dim", "维度", 150, "left"),
    ("field", "字段", 150, "left"),
    ("type", "类型", 70, "center"),
    ("hit", "命中/总数", 90, "center"),
    ("bar", "覆盖", 170, "center"),
    ("missing", "未命中取值", 380, "left"),
)

BAR_WIDTH = 10


def _bar(ratio: float) -> str:
    filled = int(round(max(0.0, min(1.0, ratio)) * BAR_WIDTH))
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def _coverage_text(ratio: float) -> str:
    """百分比**放在方条前面**。

    方条用的是 `█`(U+2588)，在中文界面字体（微软雅黑那一串）里是**全宽**字符，
    十个方块实际占二十列 —— 按等宽字体量的列宽必然估小。表格默认从尾部省略，
    于是被切掉的正好是百分比，而这一列的百分比才是「覆盖率收敛」要看的东西。
    把数字放前面：真要省略，省略掉的也只是方条。
    """
    return f"{ratio:.0%} {_bar(ratio)}"


class CoveragePage(Page):
    TITLE = "取值覆盖"
    HINT = ("分母是字段声明的取值点，分子是被 case 命中的。覆盖为 0 的维度通常意味着"
            "它没有被任何专题选中；联动派生字段标灰 —— 它的取值跟随被联动字段，"
            "不是独立的缺口。")

    def build(self) -> None:
        outer = self.frame()
        outer.addWidget(self.hint_label())

        splitter = QSplitter(Qt.Orientation.Vertical)

        chart_box = QScrollArea()
        chart_box.setWidgetResizable(True)
        self.chart = CoverageView()
        chart_box.setWidget(self.chart)
        splitter.addWidget(chart_box)

        self.model = RowsModel(FIELD_COLUMNS, self)
        self.view = self.make_table(self.model)
        splitter.addWidget(self.view)
        splitter.setSizes([260, 340])
        outer.addWidget(splitter, 1)

    def refresh(self, result) -> None:
        self.chart.set_coverage(result.dimension_coverage)

        rows, colors = [], {}
        for dim in result.dimension_coverage:
            for f in dim.fields:
                rows.append({
                    "dim": dim.name, "field": f.field, "type": f.type_name,
                    "hit": f"{f.hit_count}/{f.total}",
                    "bar": _coverage_text(f.ratio),
                    "missing": ("（联动派生，跟随被联动字段）" if f.derived
                                else "、".join(f.missing) or "—"),
                })
                i = len(rows) - 1
                if f.derived:
                    colors[(i, 4)] = theme.COVERAGE["derived"]
                    colors[(i, 5)] = theme.COVERAGE["derived"]
                elif f.full:
                    colors[(i, 4)] = theme.COVERAGE["full"]
                elif f.hit_count:
                    colors[(i, 4)] = theme.SEVERITY["warning"]
                else:
                    colors[(i, 4)] = theme.SEVERITY["error"]
        self.model.set_rows(rows, cell_colors=colors)

    def clear(self) -> None:
        self.chart.set_coverage([])
        self.model.set_rows([])
