"""运行历史 —— 左窗格里的那棵树：上面是"有哪些运行"，下面是"这次跑到哪了"。

一个刻意的设计：**"正在跑的"和"跑完的"是同一棵树里的同一类条目。**

判据用的是 `docs/run_events.jsonl`（跑着就有）而不是 `docs/manifest.json`
（跑完才写）。否则正在跑的那次根本不在列表里 —— 而"我现在这次跑到哪了"
恰恰是打开界面最想问的问题。

选中一条会往总线上发 `run.selected`。其他视图（阶段时间线、证据、覆盖率趋势）
据此跟着切 —— 模块之间不互相 import，全靠这条明文的字符串话题。
"""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .... import bus
from ....ui import theme
from ...base import ModuleBase
from ..run_common import run_label, run_tooltip, status_color

RUN_ROLE = Qt.ItemDataRole.UserRole + 1


class RunsModule(ModuleBase):
    """运行列表 —— 选中的运行会广播给其它视图。"""

    HINT = "左边列出所有运行（含正在跑的）。选一条，右侧的时间线与证据会跟着切。"

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel(self.HINT, root)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(hint)

        bar = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新", root)
        self.btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.btn_refresh)
        self.btn_latest = QPushButton("跟随最新", root)
        self.btn_latest.setCheckable(True)
        self.btn_latest.setChecked(True)
        self.btn_latest.setToolTip("运行结束时自动选中最新的一次")
        bar.addWidget(self.btn_latest)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.tree = QTreeWidget(root)
        self.tree.setHeaderLabels(["运行 / 阶段", ""])
        self.tree.setColumnWidth(0, 240)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.tree, 1)

        self.count_label = QLabel("", root)
        self.count_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.count_label)
        return root

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新运行列表", self.content)
        action.triggered.connect(self.refresh)
        return [action]

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def on_activated(self) -> None:
        self.refresh()

    def on_refresh(self, payload: Any = None) -> None:
        self.refresh()

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def refresh(self) -> None:
        payload = self.run_tool("pipeline.runs", limit=100)
        if payload is None:
            return
        if self.report_payload_error(payload):
            return
        runs = payload.get("runs", []) if isinstance(payload, dict) else []
        current = self.selected_run_id()
        self._fill(runs, select=current or self._latest_id(runs))
        self.count_label.setText(
            f"{len(runs)} 次运行"
            + (f"　当前：{payload.get('current')}" if payload.get("current") else ""))

    def _latest_id(self, runs: List[Dict[str, Any]]) -> str:
        if not self.btn_latest.isChecked() or not runs:
            return ""
        return str(runs[0].get("run_id", ""))

    def _fill(self, runs: List[Dict[str, Any]], *, select: str = "") -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        for run in runs:
            item = QTreeWidgetItem(self.tree, [run_label(run),
                                               str(run.get("state", ""))])
            item.setData(0, RUN_ROLE, run)
            item.setToolTip(0, run_tooltip(run))
            item.setForeground(1, self._brush(status_color(str(run.get("state", "")))))
            for stage in run.get("stages", []) or []:
                child = QTreeWidgetItem(item, [
                    f"　{stage.get('title') or stage.get('stage', '')}",
                    str(stage.get("status", ""))])
                child.setForeground(1, self._brush(status_color(
                    str(stage.get("status", "")))))
            item.setExpanded(True)
            if select and str(run.get("run_id", "")) == select:
                item.setSelected(True)
        self.tree.blockSignals(False)
        if select:
            self._publish(select)

    @staticmethod
    def _brush(color: str):
        from PySide6.QtGui import QBrush, QColor
        return QBrush(QColor(color))

    # ════════════════════════════════════════════════════════
    # 选择
    # ════════════════════════════════════════════════════════

    def selected_run_id(self) -> str:
        items = self.tree.selectedItems()
        if not items:
            return ""
        item = items[0]
        while item.parent() is not None:
            item = item.parent()
        run = item.data(0, RUN_ROLE) or {}
        return str(run.get("run_id", ""))

    def _on_selection(self) -> None:
        run_id = self.selected_run_id()
        if run_id:
            self._publish(run_id)

    def _publish(self, run_id: str) -> None:
        self.ctx.bus.publish(bus.TOPIC_RUN_SELECTED, run_id)
        self.set_status(f"选中运行 {run_id}")
