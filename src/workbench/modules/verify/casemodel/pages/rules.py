"""规则清单 —— 从规格注册表读，永远不会与实现漂移。

新增一条规则只需在 `analysis/rules/` 下写一个 Rule 子类，这一页自动多一行。
"""
from __future__ import annotations

from src.tools.generation.casemodel_tools.analysis import rule_docs
from src.tools.generation.casemodel_tools.analysis.issues import CATEGORY_NAMES
from src.workbench.ui import theme
from src.workbench.ui.models import RowsModel

from ..page import Page

COLUMNS = (
    ("category", "分类", 140, "left"),
    ("rule", "规则", 300, "left"),
    ("severity", "严重度", 80, "center"),
    ("description", "说明", 620, "left"),
)


class RulesPage(Page):
    TITLE = "规则清单"
    HINT = ("全部校验规则，按分类列出。规则由 analysis/rules/ 下的 Rule 子类"
            "自动登记 —— 这一页读的是注册表，不是手写的清单。")

    def build(self) -> None:
        outer = self.frame()
        outer.addWidget(self.hint_label())
        self.model = RowsModel(COLUMNS, self)
        self.view = self.make_table(self.model)
        outer.addWidget(self.view, 1)

    def refresh(self, result) -> None:
        docs = rule_docs()
        rows = [{"category": CATEGORY_NAMES.get(cat, cat), "rule": rid,
                 "severity": sev, "description": desc}
                for rid, sev, cat, desc in docs]
        colors = {i: theme.SEVERITY.get(sev, theme.TEXT)
                  for i, (_r, sev, _c, _d) in enumerate(docs)}
        self.model.set_rows(rows, cell_colors={(i, 2): c for i, c in colors.items()})

    def clear(self) -> None:
        self.model.set_rows([])
