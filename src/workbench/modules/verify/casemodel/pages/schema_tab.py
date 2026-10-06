"""Schema 校验 —— 原始 YAML 的语法/类型/必填/形状。"""
from __future__ import annotations

from src.workbench.ui.widgets.panels import IssuePanel

from ..page import Page


class SchemaPage(Page):
    TITLE = "Schema 校验"
    HINT = ("用 schema/case_model.schema.json 校验原始 YAML。schema 只回答"
            "「文档写对了吗」；引用是否存在、层级是否错位由其它页面回答。")

    def build(self) -> None:
        outer = self.frame()
        self.panel = IssuePanel(
            self.HINT,
            empty_hint="schema 校验通过（语法 / 类型 / 必填 / 类型化取值表形状）。",
            parent=self)
        outer.addWidget(self.panel)

    def refresh(self, result) -> None:
        self.panel.set_issues(self.module.schema_issues)

    def clear(self) -> None:
        self.panel.clear()
