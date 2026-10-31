"""SoC 签核 —— 工程级证据包与事实面入口（不是 UVM v2 三态签核）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...ui import theme
from .common import SocModuleBase


class SoCSignoffModule(SocModuleBase):
    HINT = ("SoC 证据包（soc_evidence_v1）：输入 / RTL / golden / 回归 / 波形。"
            "它是工程级事实，不是 UVM 的 TP 矩阵 + caveat 三态签核。")

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addWidget(self._run_bar(root))
        self.body = QLabel("尚未选择 SoC run", root)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.body)

        row = QHBoxLayout()
        row.addWidget(self._button("校验证据包", self.verify_evidence, root))
        row.addWidget(self._button("打开波形", self.open_wave, root))
        row.addWidget(self._button("证据 / 产物", lambda: self._open("flow.evidence"), root))
        row.addWidget(self._button("签核判定", lambda: self._open("flow.signoff"), root))
        row.addWidget(self._button("复制证据目录", self._copy_dir, root))
        row.addStretch(1)
        layout.addLayout(row)
        self.refresh()
        return root

    def _open(self, module_id: str) -> None:
        from ..service.common import open_module
        open_module(self.ctx, module_id)

    def _copy_dir(self) -> None:
        root = self.current_dir()
        if root:
            QApplication.clipboard().setText(str(Path(root) / "signoff_evidence"))

    def on_summary(self, summary: Dict[str, Any]) -> None:
        doc = (summary or {}).get("manifest") or {}
        if not doc:
            self.body.setText("还没有 SoC run。")
            return
        ev = (summary or {}).get("evidence") or {}
        reg = doc.get("regression") or {}
        waves = doc.get("waves") or []
        self.body.setText(
            f"run：{doc.get('run', {}).get('run_id') or summary.get('dir')}\n"
            f"回归：{reg.get('status')} · {reg.get('passed')}/{reg.get('total')}\n"
            f"证据包：{'✓' if ev.get('ok') else '✗'} {ev.get('files', 0)} 个文件 · "
            f"package_hash {str(ev.get('package_hash'))[:16]}…\n"
            f"波形：{waves[0].get('path') if waves else '无'}\n"
            f"目录：{Path(summary.get('dir', '')) / 'signoff_evidence'}")
        self.body.setStyleSheet(f"color: {theme.current().muted};")
