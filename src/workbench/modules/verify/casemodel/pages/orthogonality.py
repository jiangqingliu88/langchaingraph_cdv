"""层级正交性 —— 文档十八、十九节的三类错位。"""
from __future__ import annotations

from src.tools.generation.casemodel_tools.analysis import CATEGORY_ORTHOGONAL
from src.workbench.ui.widgets.panels import IssuePanel

from ..page import Page


class OrthogonalityPage(Page):
    TITLE = "层级正交性"
    HINT = ("判据只有一条：同一个信息只能存在于一个层级。抓四类错位 —— "
            "把字段当维度 / 把维度当对象 / 把方法当维度 / 把检查当对象。"
            "「反压持续时间」里的「持续」只是构词成分，不会被误报。")

    def build(self) -> None:
        outer = self.frame()
        self.panel = IssuePanel(
            self.HINT, empty_hint="没有发现层级错位。", parent=self)
        outer.addWidget(self.panel)

    def refresh(self, result) -> None:
        self.panel.set_issues(
            result.by_category().get(CATEGORY_ORTHOGONAL, []))

    def clear(self) -> None:
        self.panel.clear()
