"""证据 / 产物 —— 右窗格：这次运行到底留下了什么。

「签核证据包」是本项目的核心承诺，所以这一页要回答的是最直接的那个问题：
**这次运行产出了哪些文件，它们在哪，能不能被验证。**

刻意分成两页：

  · 「产物」——`output/{run}/` 下的文件树。这一页的价值在于**没有过滤**：
    证据链的要害是"该有的都在"，而不是"摘要好看"。
  · 「覆盖率」——`coverage_history` 的逐轮变化。它属于"过程"而不是"产物"，
    所以从运行日志里取，跑着就能看到曲线在动。
"""
from __future__ import annotations

from src.workbench.bus import run_id_of

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QLabel, QPlainTextEdit, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .... import bus
from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import LEFT, RowsModel
from ...base import ModuleBase
from ..run_common import kind_label, one_line, status_color

FILE_ROLE = Qt.ItemDataRole.UserRole + 1

COVERAGE_COLUMNS = (("轮次", "轮次", 70, LEFT), ("总覆盖率", "总覆盖率", 110, LEFT),
                    ("功能覆盖率", "功能覆盖率", 120, LEFT))


class EvidenceModule(ModuleBase):
    """一次运行的产物树与覆盖率轨迹。"""

    HINT = ("这次运行留下了哪些文件。证据链的要害是「该有的都在」，"
            "所以这一页不做过滤 —— 只按目录分组。")

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        self.run_id: str = ""

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel(self.HINT, root)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(hint)

        self.title_label = QLabel("（还没选中运行）", root)
        layout.addWidget(self.title_label)

        tabs = QTabWidget(root)
        tabs.addTab(self._build_files_page(), "产物")
        tabs.addTab(self._build_coverage_page(), "覆盖率")
        layout.addWidget(tabs, 1)
        return root

    def _build_files_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.tree = QTreeWidget(page)
        self.tree.setHeaderLabels(["文件", "大小"])
        self.tree.setColumnWidth(0, 220)
        self.tree.setUniformRowHeights(True)
        self.tree.itemSelectionChanged.connect(self._show_file)
        layout.addWidget(self.tree, 1)

        self.preview = QPlainTextEdit(page)
        self.preview.setReadOnly(True)
        self.preview.setFont(theme.mono_font())
        self.preview.setPlaceholderText("选一个文本文件，这里显示开头一段")
        self.preview.setMaximumHeight(160)
        layout.addWidget(self.preview)
        return page

    def _build_coverage_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        self.coverage_model = RowsModel(COVERAGE_COLUMNS, page)
        self.coverage_table = table_helpers.configure_table(page,
                                                            self.coverage_model)
        layout.addWidget(self.coverage_table, 1)
        return page

    def create_actions(self) -> List[QAction]:
        action = QAction("刷新证据", self.content)
        action.triggered.connect(lambda: self.load(self.run_id))
        return [action]

    def on_activated(self) -> None:
        if self.run_id:
            self.load(self.run_id)

    def on_refresh(self, payload: Any = None) -> None:
        """`run.selected` 的订阅者。"""
        run_id = run_id_of(payload)
        if run_id and run_id != self.run_id:
            self.load(run_id)

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def load(self, run_id: str) -> None:
        if not run_id:
            return
        payload = self.run_tool("pipeline.detail", quiet=True, run_id=run_id)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            return
        self.run_id = run_id
        state = {"completed": "已完成", "failed": "失败", "cancelled": "已取消",
                 "running": "运行中"}.get(str(payload.get("state", "")), "")
        self.title_label.setText(f"{run_id}　{state}")
        self.title_label.setStyleSheet(f"color: {status_color(payload.get('state', ''))};")
        self._fill_files(str(payload.get("dir", "")))
        self._fill_coverage(payload.get("events") or [])

    def _fill_files(self, run_dir: str) -> None:
        self.tree.clear()
        root = Path(run_dir) if run_dir else None
        if not root or not root.is_dir():
            self._add_note(f"找不到产物目录：{run_dir or '（未知）'}")
            return
        self._add_directory(self.tree, root)
        self.tree.expandToDepth(1)

    def _add_note(self, text: str) -> None:
        item = QTreeWidgetItem(self.tree, [text, ""])
        item.setForeground(0, self._brush(theme.current().muted))

    def _add_directory(self, parent, directory: Path) -> None:
        """递归铺目录。

        证据链要看的是"该有的都在"，所以**不做过滤、不隐藏空目录** ——
        文件少了本身就是要看见的信号。
        """
        try:
            children = sorted(directory.iterdir(),
                              key=lambda p: (p.is_file(), p.name))
        except OSError as exc:
            self._add_note(f"（读不了：{exc}）")
            return
        for child in children:
            if child.is_dir():
                node = QTreeWidgetItem(parent, [child.name + "/", ""])
                node.setForeground(0, self._brush(theme.current().accent))
                self._add_directory(node, child)
            else:
                try:
                    size_kb = round(child.stat().st_size / 1024, 1)
                except OSError:
                    size_kb = 0.0
                node = QTreeWidgetItem(parent, [child.name, f"{size_kb} KB"])
                node.setData(0, FILE_ROLE, str(child))

    def _fill_coverage(self, events: List[Dict[str, Any]]) -> None:
        """覆盖率事件 → 一张逐轮的表。

        从日志来而不是从产物来：产物要跑完才有，而曲线跑着就该能看。
        """
        rows = []
        for event in events:
            if event.get("kind") != "coverage.updated":
                continue
            payload = event.get("payload") or {}
            # 与 StageTimeline 同一口径：`round` 本身就是 1-based（见 run_common）
            rows.append({
                "轮次": str(max(1, int(event.get("round", 0) or 0))),
                "总覆盖率": f"{payload.get('total', 0)}%",
                "功能覆盖率": f"{payload.get('functional', 0)}%",
            })
        self.coverage_model.set_rows(rows)

    # ════════════════════════════════════════════════════════
    # 预览
    # ════════════════════════════════════════════════════════

    def _show_file(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        path = items[0].data(0, FILE_ROLE)
        if not path:
            self.preview.clear()
            return
        target = Path(path)
        if target.suffix.lower() in (".zip", ".db", ".vcd", ".fsdb"):
            self.preview.setPlainText(f"（{target.suffix} 是二进制，不在这里预览）")
            return
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.preview.setPlainText(f"读不了：{exc}")
            return
        lines = text.splitlines()
        head = "\n".join(lines[:80])
        if len(lines) > 80:
            head += f"\n… 共 {len(lines)} 行，只显示前 80 行"
        self.preview.setPlainText(head)

    @staticmethod
    def _brush(color: str):
        from PySide6.QtGui import QBrush, QColor
        return QBrush(QColor(color))
