"""IP 发布检查 —— 发布前的结构化清单，不冒充签核结论。"""
from __future__ import annotations

from typing import Any, Dict

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...ui import theme
from ..service.common import open_module
from .common import IpModuleBase


class IpSignoffModule(IpModuleBase):
    HINT = ("IP 团队视角：发布前检查（spec / RTL / verification plan / 状态）。"
            "这是人工发布门禁；自动签核证据仍以 run 的 evidence 为准。")

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("IP"))
        self.combo = QComboBox(root)
        self.combo.setMinimumWidth(320)
        self.combo.currentIndexChanged.connect(self._show)
        row.addWidget(self.combo, 1)
        refresh = QPushButton("刷新", root)
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)

        self.body = QLabel("", root)
        self.body.setWordWrap(True)
        layout.addWidget(self.body)

        links = QHBoxLayout()
        evidence = QPushButton("证据 / 产物", root)
        evidence.clicked.connect(lambda: open_module(self.ctx, "flow.evidence"))
        links.addWidget(evidence)
        signoff = QPushButton("SoC 签核", root)
        signoff.clicked.connect(lambda: open_module(self.ctx, "soc.signoff"))
        links.addWidget(signoff)
        links.addStretch(1)
        layout.addLayout(links)
        self.refresh()
        return root

    def refresh(self) -> None:
        current = str(self.combo.currentData() or "")
        ips = self.load_ips()
        self.combo.blockSignals(True)
        self.combo.clear()
        for ip in ips:
            self.combo.addItem(str(ip.get("id")), ip.get("id"))
        idx = self.combo.findData(current)
        self.combo.setCurrentIndex(idx if idx >= 0 and self.combo.count() else 0)
        self.combo.blockSignals(False)
        self._show(self.combo.currentIndex())

    def _show(self, _index: int) -> None:
        ip_id = str(self.combo.currentData() or "")
        if not ip_id:
            self.body.setText("没有 IP 清单。")
            return
        ip = self.ip_info(ip_id)
        checks = [
            ("spec", bool(ip.get("spec"))),
            ("RTL 齐全", not ip.get("rtl_missing") and bool(ip.get("rtl_files"))),
            ("verification plan", bool(ip.get("verification"))),
            ("发布状态 released", ip.get("status") == "released"),
        ]
        self.body.setText(
            f"{ip.get('id')} · {ip.get('name')} · {ip.get('team') or '?'}\n"
            + "\n".join(f"{'✓' if ok else '✗'} {name}" for name, ok in checks)
            + "\n\n边界：IP 级自动证据包尚未接入；"
              "当前证据入口是 run 的 `signoff_evidence/`，不是 IP 发布签核。")
        self.body.setStyleSheet(f"color: {theme.current().muted};")
