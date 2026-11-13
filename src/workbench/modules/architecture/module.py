"""Architecture 4.0 总览 —— 8 个职责平面 + Workbench 的边界与 Guard 状态。"""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..base import ModuleBase


class ArchitecturePlaneModule(ModuleBase):
    HINT = ("Workbench 属于 Interfaces Plane：CLI 是正式入口，GUI 只是外壳；"
            "这里只读架构状态，不执行验证。")

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.status = QLabel("", root)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 5, root)
        self.table.setHorizontalHeaderLabels(
            ["平面", "职责", "禁止", "文件", "目录"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.refresh_button = QPushButton("重新检查 Guard", root)
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.detail = QTextEdit(root)
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(150)
        layout.addWidget(self.detail)

        self.refresh()
        return root

    def refresh(self) -> None:
        self.on_refresh()

    def on_refresh(self, payload: Any = None) -> None:
        data = self.run_tool("architecture.snapshot", quiet=True)
        if not data:
            self.status.setText("architecture.snapshot 不可用（检查 bridge/catalog 绑定）")
            return
        planes = data["planes"]
        self.table.setRowCount(len(planes) + 1)
        for row, plane in enumerate(planes):
            values = [plane["key"], plane["responsibility"], plane["must_not"],
                      str(plane["files"]), plane["dir"]]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
        wb = data["workbench"]
        values = ["Workbench (Interfaces)", "CLI / API / GUI 入口",
                  "不拥有独立验证引擎", str(wb["files"]), wb["dir"]]
        last = len(planes)
        for col, value in enumerate(values):
            self.table.setItem(last, col, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

        guard = data["guard"]
        if guard["ok"]:
            self.status.setText(f"Guard {guard['version']}：OK —— 预算、依赖、债务均在约束内")
            self.status.setStyleSheet("color: #2e7d32;")
        else:
            total = sum(len(guard[k]) for k in
                        ("line_issues", "complexity_issues", "zone_issues",
                         "import_issues", "cycle_issues", "debt_issues"))
            total += len(guard["unzoned_files"])
            self.status.setText(f"Guard {guard['version']}：FAIL —— {total} 条违规")
            self.status.setStyleSheet("color: #c62828;")

        lines = []
        for key in ("line_issues", "complexity_issues", "zone_issues",
                    "import_issues", "cycle_issues", "debt_issues"):
            for issue in guard[key][:8]:
                lines.append(f"[{key}] {issue}")
        self.detail.setPlainText("\n".join(lines) if lines else "没有 Guard 违规。")
