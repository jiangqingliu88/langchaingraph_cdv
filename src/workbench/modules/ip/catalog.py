"""IP 目录 —— 每个 IP 的团队、发布状态与 RTL 完整性。"""
from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ...ui import theme
from .common import IpModuleBase

COLUMNS = ("IP", "名称", "团队", "Owner", "版本", "状态", "RTL")


class IpCatalogModule(IpModuleBase):
    HINT = "IP 团队视角：谁负责哪个 IP、发布状态、RTL 是否齐全。选中一行打开工作区。"

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)

        self.summary = QLabel("", root)
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, len(COLUMNS), root)
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._open)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        from PySide6.QtWidgets import QPushButton
        refresh = QPushButton("刷新", root)
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        open_btn = QPushButton("打开 IP 工作区", root)
        open_btn.clicked.connect(lambda: self._open())
        row.addWidget(open_btn)
        row.addStretch(1)
        layout.addLayout(row)
        self.refresh()
        return root

    def refresh(self) -> None:
        ips = self.load_ips()
        self.table.setRowCount(len(ips))
        by_team: Dict[str, int] = {}
        for row, ip in enumerate(ips):
            by_team[str(ip.get("team") or "?")] = by_team.get(
                str(ip.get("team") or "?"), 0) + 1
            missing = ip.get("rtl_missing") or []
            values = (ip.get("id", ""), ip.get("name", ""), ip.get("team", ""),
                      ip.get("owner", ""), ip.get("version", ""),
                      ip.get("status", ""),
                      f"{len(ip.get('rtl_present') or [])}/{len(ip.get('rtl_files') or [])}"
                      + ("（缺）" if missing else ""))
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 5:
                    color = theme.current().ok if value == "released" else theme.current().warning
                    item.setForeground(QBrush(QColor(color)))
                self.table.setItem(row, col, item)
        self.summary.setText(
            f"{len(ips)} 个 IP · " + " · ".join(f"{k} {v}" for k, v in sorted(by_team.items())))
        self.set_status(f"IP 目录：{len(ips)} 个")

    def _open(self, row: int = -1, _col: int = 0) -> None:
        from ..service.common import open_module
        row = row if row >= 0 else self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 0)
            if item is not None:
                self.ctx.selected_ip = item.text()
        open_module(self.ctx, "ip.workspace")
