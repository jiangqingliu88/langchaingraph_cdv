"""IP 工作区 —— 选中 IP 的规格、RTL、验证入口。"""
from __future__ import annotations

from typing import Any, Dict

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...ui import theme
from ..service.common import open_module
from .common import IpModuleBase


class IpWorkspaceModule(IpModuleBase):
    HINT = "IP 团队视角：选中一个 IP，查看它的 RTL / spec / 验证计划并跳到现有专业模块。"

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("IP"))
        self.combo = QComboBox(root)
        self.combo.setMinimumWidth(320)
        self.combo.currentIndexChanged.connect(self._ip_changed)
        row.addWidget(self.combo, 1)
        from PySide6.QtWidgets import QPushButton
        refresh = QPushButton("刷新", root)
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)

        self.info = QLabel("", root)
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        label = QLabel("RTL", root)
        label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(label)
        self.table = QTableWidget(0, 2, root)
        self.table.setHorizontalHeaderLabels(["文件", "存在"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        links = QHBoxLayout()
        for text, module_id in (("设计产出", "design.output"), ("验证产出", "verify.output"),
                                ("回归状态", "ops.regression_status"),
                                ("覆盖率", "coverage.output"), ("调试", "debug.output")):
            link = QPushButton(text, root)
            link.clicked.connect(lambda _=False, mid=module_id: open_module(self.ctx, mid))
            links.addWidget(link)
        links.addStretch(1)
        layout.addLayout(links)
        self.refresh()
        return root

    def refresh(self) -> None:
        current = str(self.combo.currentData() or getattr(self.ctx, "selected_ip", "") or "")
        ips = self.load_ips()
        self.combo.blockSignals(True)
        self.combo.clear()
        for ip in ips:
            self.combo.addItem(f"{ip.get('id')} · {ip.get('name')}", ip.get("id"))
        idx = self.combo.findData(current)
        self.combo.setCurrentIndex(idx if idx >= 0 and self.combo.count() else 0)
        self.combo.blockSignals(False)
        self._ip_changed(self.combo.currentIndex())

    def _ip_changed(self, _index: int) -> None:
        ip_id = str(self.combo.currentData() or "")
        if not ip_id:
            self.info.setText("没有 IP 清单（spec/ip_manifest.yaml）")
            return
        ip = self.ip_info(ip_id)
        self.info.setText(
            f"{ip.get('id')} · {ip.get('name')}\n"
            f"团队：{ip.get('team') or '?'} · Owner：{ip.get('owner') or '?'} · "
            f"版本：{ip.get('version') or '?'} · 状态：{ip.get('status') or '?'}\n"
            f"RTL hash：{str(ip.get('rtl_hash'))[:16]}… · "
            f"spec：{ip.get('spec') or '-'} · verification：{ip.get('verification') or '-'}\n"
            f"{ip.get('notes') or ''}")
        files = ip.get("rtl_files") or []
        present = set(ip.get("rtl_present") or [])
        self.table.setRowCount(len(files))
        for row, rel in enumerate(files):
            self.table.setItem(row, 0, QTableWidgetItem(str(rel)))
            self.table.setItem(row, 1, QTableWidgetItem("✓" if rel in present else "✗"))
        self.set_status(f"IP 工作区：{ip_id}")
