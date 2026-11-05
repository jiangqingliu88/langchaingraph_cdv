"""SoC 架构 —— RTL 模块、接口与地址映射（只读）。"""
from __future__ import annotations

from typing import Any, Dict

from PySide6.QtWidgets import (QAbstractItemView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...ui import theme
from .common import SocModuleBase


class SoCArchitectureModule(SocModuleBase):
    HINT = "SoC 的模块、接口和地址映射；由 spec/interface_spec 与 RTL 文件清单生成。"

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.info = QLabel("", root)
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        layout.addWidget(self._section("RTL 模块", root))
        self.rtl = self._table(("文件", "目录"), root)
        layout.addWidget(self.rtl, 2)

        layout.addWidget(self._section("接口 / 地址映射", root))
        self.iface = self._table(("名称", "协议 / 方向 / 说明"), root)
        layout.addWidget(self.iface, 2)

        payload = self.run_tool("soc.project", quiet=True,
                                root=str(self.project_root))
        self._fill(payload if isinstance(payload, dict) else {})
        return root

    def _section(self, text: str, parent) -> QLabel:
        label = QLabel(text, parent)
        label.setStyleSheet(f"color: {theme.current().muted};")
        return label

    def _table(self, headers, parent) -> QTableWidget:
        table = QTableWidget(0, len(headers), parent)
        table.setHorizontalHeaderLabels(list(headers))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _fill(self, info: Dict[str, Any]) -> None:
        if not info:
            self.info.setText("读不到 SoC 工程输入。")
            return
        self.info.setText(f"{info.get('name')} · RTL hash {str(info.get('rtl_hash'))[:16]}…")
        files = info.get("rtl_files") or []
        self.rtl.setRowCount(len(files))
        for row, rel in enumerate(files):
            self.rtl.setItem(row, 0, QTableWidgetItem(str(rel)))
            self.rtl.setItem(row, 1, QTableWidgetItem(str(rel).rsplit("/", 1)[0]))

        rows = []
        for item in info.get("interface_spec", {}).get("interfaces") or []:
            if isinstance(item, dict):
                rows.append((item.get("name") or "-",
                             f"{item.get('protocol') or '-'} / "
                             f"{item.get('direction') or '-'} / "
                             f"{item.get('description') or ''}"))
        spec_map = info.get("spec", {}).get("address_map") or {}
        for name, addr in (spec_map.items() if isinstance(spec_map, dict) else []):
            rows.append((str(name), f"地址 {addr}"))
        self.iface.setRowCount(len(rows))
        for row, (name, desc) in enumerate(rows):
            self.iface.setItem(row, 0, QTableWidgetItem(name))
            self.iface.setItem(row, 1, QTableWidgetItem(desc))
