"""概览 —— 分层结构与评分拆解。

一屏回答两个问题：「这个模型由什么组成」和「它哪里扣分了」。
评分拆解带扣分原因 —— 一个不能解释的数字没法行动。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget

from src.workbench.ui import theme
from src.workbench.ui.models import RowsModel

from ..page import Page

LAYER_COLUMNS = (
    ("layer", "层", 46, "center"),
    ("name", "名称", 190, "left"),
    ("role", "作用", 150, "left"),
    ("count", "数量", 54, "center"),
    ("detail", "明细", 520, "left"),
)
SCORE_COLUMNS = (
    ("item", "评分项", 110, "left"),
    ("sub", "子分", 60, "center"),
    ("weighted", "加权", 60, "center"),
    ("reason", "扣分原因", 460, "left"),
)

#: 分数三档的门槛。优良中差的分界是业务判断，留在这里；
#: 「良好是什么颜色」是外观，跟着主题走。
GRADE_THRESHOLDS = ((85, "GRADE_GOOD"), (60, "GRADE_WARN"))


def _grade_color(score: float):
    for threshold, name in GRADE_THRESHOLDS:
        if score >= threshold:
            return getattr(theme, name)
    return theme.GRADE_BAD


def _score_style(color) -> str:
    """大分数的样式 —— 字号取自主题常量，免得各页各写一个。"""
    return (f"font-size: {theme.SCORE_SIZE}pt; font-weight: bold; "
            f"color: {color.name()};")


class OverviewPage(Page):
    TITLE = "概览"
    HINT = ("八层属性结构 + 环境的逐层统计，以及八项子分加权成的完备性总分。"
            "评分是模型的属性：同一份模型无论传哪份外部 case 列表，分数都一样。")

    def build(self) -> None:
        outer = self.frame()

        head = QHBoxLayout()
        self.score_label = QLabel("—")
        self.score_label.setStyleSheet(_score_style(theme.GRADE_GOOD))
        head.addWidget(self.score_label)
        self.summary_label = QLabel("")
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(self.summary_label, 1)
        outer.addLayout(head)

        splitter = QSplitter(Qt.Orientation.Vertical)

        layer_box = QWidget()
        layer_layout = QVBoxLayout(layer_box)
        layer_layout.setContentsMargins(0, 0, 0, 0)
        layer_layout.addWidget(self.section_label("分层结构　L1 → L6 + 专题 + 环境"))
        self.layer_model = RowsModel(LAYER_COLUMNS, self)
        self.layer_view = self.make_table(self.layer_model)
        layer_layout.addWidget(self.layer_view, 1)
        splitter.addWidget(layer_box)

        score_box = QWidget()
        score_layout = QVBoxLayout(score_box)
        score_layout.setContentsMargins(0, 0, 0, 0)
        score_layout.addWidget(self.section_label("评分拆解　子分 × 权重 = 加权得分"))
        self.score_model = RowsModel(SCORE_COLUMNS, self)
        self.score_view = self.make_table(self.score_model)
        score_layout.addWidget(self.score_view, 1)
        splitter.addWidget(score_box)

        splitter.setSizes([380, 320])
        outer.addWidget(splitter, 1)

    def refresh(self, result) -> None:
        score = result.score.total
        self.score_label.setText(f"{score:.0f}")
        self.score_label.setStyleSheet(_score_style(_grade_color(score)))

        s = result.summary()
        gen = result.generation
        self.summary_label.setText("\n".join([
            f"{result.model.object_label}　　版本 {result.model.version or '—'}",
            f"组织树 {s['org_leaf_count']} 个叶子　　专题 {s['theme_count']} 个"
            f"（{'、'.join(gen.priorities_used) or '—'}）　　驱动 {gen.driver}",
            f"case {s['case_count']} 个"
            + (f"（组合规模 {s['case_total_before_cap']}，截断丢弃 {s['dropped']}）"
               if s["truncated"] else "")
            + f"　　seed {gen.seed}",
            f"取值覆盖 {result.coverage_ratio:.1%}　　错误 {s['error_count']} / "
            f"警告 {s['warning_count']} / 提示 {s['info_count']}",
        ]))

        self.layer_model.set_rows(result.model.layer_rows())

        rows = []
        colors = {}
        for i, (name, sub, weighted, reasons) in enumerate(result.score.row_reasons()):
            rows.append({"item": name, "sub": f"{sub:.2f}", "weighted": f"{weighted:.1f}",
                         "reason": "；".join(reasons) or "—"})
            colors[i] = (theme.COVERAGE["full"] if sub >= 0.85
                         else theme.SEVERITY["warning"] if sub >= 0.5
                         else theme.SEVERITY["error"])
        self.score_model.set_rows(rows, cell_colors={(i, 0): c for i, c in colors.items()})

    def clear(self) -> None:
        self.layer_model.set_rows([])
        self.score_model.set_rows([])
        self.score_label.setText("—")
        self.summary_label.clear()
