"""可复用面板 —— 「提示 + 一张表」这种形状的页面。

诊断类页面有 3 个（正交性 / Schema / 环境），行表类页面有 4 个（检查项 / 规则 /
专题规模 / 外部汇总），形状完全一样。抽成面板之后，那些页面只剩「取数据 → 塞进去」。

面板不含判定逻辑：给什么数据就显示什么。
"""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QTableView, QVBoxLayout, QWidget

from . import theme
from .models import RowsModel, SortProxy
from .severity_model import IssueTableModel


class _Panel(QWidget):
    """提示 + 统计行 + 一张表。"""

    def __init__(self, hint: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if hint:
            label = QLabel(hint)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {theme.MUTED.name()};")
            layout.addWidget(label)
        self.summary = QLabel("")
        self.summary.setStyleSheet(f"color: {theme.MUTED.name()};")
        layout.addWidget(self.summary)

        self.view = QTableView(self)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.view.setWordWrap(False)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(theme.ROW_HEIGHT)
        self.view.horizontalHeader().setHighlightSections(False)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.setShowGrid(True)
        layout.addWidget(self.view, 1)

        self._empty_hint = "（无）"
        self.model = None
        self.proxy = None

    def _set_model(self, model, sortable: bool = True) -> None:
        """挂上源模型，并按需包一层排序代理（点表头排序，原序不受影响）。"""
        self.model = model
        if sortable:
            self.proxy = SortProxy(self.view)
            self.proxy.setSourceModel(model)
            self.view.setModel(self.proxy)
            self.view.setSortingEnabled(True)          # 开了能力就复位，别自动排
            self.view.horizontalHeader().setSortIndicator(
                -1, Qt.SortOrder.AscendingOrder)
            self.proxy.sort(-1)
        else:
            self.proxy = None
            self.view.setModel(model)

    def clear(self) -> None:
        """清空面板 —— 没有分析结果时会调它。"""
        self.summary.clear()
        for setter in ("set_rows", "set_issues", "set_cases"):
            if hasattr(self.model, setter):
                getattr(self.model, setter)([])
                return


class IssuePanel(_Panel):
    """提示 + 诊断表。严重度着色与统计行由这里统一处理。

    双击一条诊断会发 `issueActivated` —— 接上「跳到 YAML 对应行」，
    就是 Verdi 那种点错误跳源码的手感。
    """

    issueActivated = Signal(object)

    def __init__(self, hint: str = "", empty_hint: str = "（无）",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(hint, parent)
        self._empty_hint = empty_hint
        model = IssueTableModel(self)
        self._set_model(model)
        model.apply_column_widths(self.view)
        self.view.doubleClicked.connect(self._on_double_click)

    def _on_double_click(self, index) -> None:
        source = self.proxy.mapToSource(index) if self.proxy else index
        issue = self.model.issue_at(source.row())
        if issue is not None:
            self.issueActivated.emit(issue)

    def set_issues(self, issues: Sequence) -> None:
        self.model.set_issues(issues)
        counts = self.model.counts()
        if not issues:
            self.summary.setText(self._empty_hint)
            return
        self.summary.setText(
            f"共 {len(issues)} 条 —— 错误 {counts['error']}　"
            f"警告 {counts['warning']}　提示 {counts['info']}")


class RowsPanel(_Panel):
    """提示 + 通用行表。"""

    def __init__(self, columns: Sequence, hint: str = "",
                 empty_hint: str = "（无）", parent: Optional[QWidget] = None) -> None:
        super().__init__(hint, parent)
        self._empty_hint = empty_hint
        model = RowsModel(columns, self)
        self._set_model(model)
        model.apply_column_widths(self.view)

    def set_rows(self, rows: Sequence, **colors) -> None:
        self.model.set_rows(rows, **colors)
        self.summary.setText(self._empty_hint if not rows else f"共 {len(rows)} 行")
