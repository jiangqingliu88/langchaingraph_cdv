"""环境与检查 —— 文档九、十节：最容易被遗漏的两层。

环境指纹决定失败 case 能不能复现；检查项决定 case 跑过之后验证了什么。
两者都不是「主体」，所以最容易被漏 —— 这一页专门给它们一个位置。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from src.layers.l3_decision.casemodel.analysis import (CATEGORY_ENVIRONMENT,
                                                CATEGORY_REFERENCE)
from src.layers.l3_decision.casemodel.domain import ENV_KEY_NAMES
from src.workbench.ui import theme
from src.workbench.ui.models import RowsModel
from src.workbench.ui.widgets.panels import IssuePanel

from ..page import Page

ENV_COLUMNS = (
    ("key", "环境键", 160, "left"),
    ("cn", "含义", 100, "left"),
    ("required", "必需", 56, "center"),
    ("value", "缺省值", 280, "left"),
    ("missing", "缺失 case", 90, "center"),
)
CHECK_COLUMNS = (
    ("id", "检查项", 160, "left"),
    ("cn", "含义", 140, "left"),
    ("used", "挂载 case 数", 110, "center"),
)


class EnvironmentPage(Page):
    TITLE = "环境与检查"
    HINT = ("环境指纹：case 不以它为主体，但执行时必须带上，失败才可复现。"
            "检查项：一个 case 往往不止一种检查（功能 / 白盒 / 性能），"
            "没挂检查的 case 跑过也不知道验证了什么。")

    def build(self) -> None:
        outer = self.frame()
        outer.addWidget(self.hint_label())

        splitter = QSplitter(Qt.Orientation.Vertical)

        top = QSplitter(Qt.Orientation.Horizontal)
        env_box = QWidget()
        env_layout = QVBoxLayout(env_box)
        env_layout.setContentsMargins(0, 0, 0, 0)
        env_layout.addWidget(self.section_label("环境指纹　复现的依据"))
        self.env_model = RowsModel(ENV_COLUMNS, self)
        self.env_view = self.make_table(self.env_model)
        env_layout.addWidget(self.env_view, 1)
        top.addWidget(env_box)

        check_box = QWidget()
        check_layout = QVBoxLayout(check_box)
        check_layout.setContentsMargins(0, 0, 0, 0)
        check_layout.addWidget(self.section_label("检查项　L6"))
        self.check_model = RowsModel(CHECK_COLUMNS, self)
        self.check_view = self.make_table(self.check_model)
        check_layout.addWidget(self.check_view, 1)
        top.addWidget(check_box)
        splitter.addWidget(top)

        self.panel = IssuePanel(empty_hint="环境指纹与检查项都齐备。", parent=self)
        splitter.addWidget(self.panel)
        splitter.setSizes([240, 300])
        outer.addWidget(splitter, 1)

    def refresh(self, result) -> None:
        model = result.model
        usage = {}
        for case in result.generation.cases:
            for cid in case.checks:
                usage[cid] = usage.get(cid, 0) + 1

        env_rows, env_colors = [], {}
        keys = list(dict.fromkeys(list(model.env_required)
                                  + list(model.case_defaults.environment)))
        for key in keys:
            missing = sum(1 for c in result.generation.cases
                          if key not in c.environment
                          or c.environment.get(key) in (None, ""))
            env_rows.append({
                "key": key, "cn": ENV_KEY_NAMES.get(key, ""),
                "required": "是" if key in model.env_required else "否",
                "value": str(model.case_defaults.environment.get(key, "（无缺省值）")),
                "missing": missing,
            })
            if missing:
                env_colors[(len(env_rows) - 1, 4)] = theme.SEVERITY["error"]
        self.env_model.set_rows(env_rows, cell_colors=env_colors)

        check_rows, check_colors = [], {}
        for cid in model.checks:
            used = usage.get(cid, 0)
            check_rows.append({"id": cid, "cn": model.check_names.get(cid, ""),
                               "used": used})
            if not used:
                check_colors[(len(check_rows) - 1, 2)] = theme.SEVERITY["warning"]
        self.check_model.set_rows(check_rows, cell_colors=check_colors)

        by_cat = result.by_category()
        self.panel.set_issues(by_cat.get(CATEGORY_ENVIRONMENT, [])
                              + by_cat.get(CATEGORY_REFERENCE, []))

    def clear(self) -> None:
        self.env_model.set_rows([])
        self.check_model.set_rows([])
        self.panel.clear()
