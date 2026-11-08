"""SoC 项目总览 —— 工程输入、最新回归、波形/证据入口。"""
from __future__ import annotations

from typing import Any, Dict

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...ui import theme
from .common import SocModuleBase


class SoCOverviewModule(SocModuleBase):
    HINT = ("Open NPU SoC 参考工程：CPU/NICE → DMA → SRAM → INT8 GEMM → IRQ → "
            "golden 比较。运行复用现有回归执行器；波形走 qwave.db。")

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.project_label = QLabel("", root)
        self.project_label.setWordWrap(True)
        layout.addWidget(self.project_label)
        layout.addWidget(self._run_bar(root))

        self.summary_label = QLabel("尚未选择 SoC run", root)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        from PySide6.QtWidgets import QHBoxLayout
        row = QHBoxLayout()
        row.addWidget(self._button("运行 SoC 回归", self.run_soc, root))
        row.addWidget(self._button("打开波形", self.open_wave, root))
        row.addWidget(self._button("校验证据包", self.verify_evidence, root))
        row.addStretch(1)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(self._button("SoC 架构", lambda: self._open("soc.architecture"), root))
        row2.addWidget(self._button("验证工作区", lambda: self._open("soc.verification"), root))
        row2.addWidget(self._button("SoC 签核", lambda: self._open("soc.signoff"), root))
        row2.addWidget(self._button("运行历史", lambda: self._open("flow.runs"), root))
        row2.addStretch(1)
        layout.addLayout(row2)

        self.hint = QLabel("", root)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.hint)
        layout.addStretch(1)

        payload = self.run_tool("soc.project", quiet=True,
                                project_root=str(self.project_root))
        if isinstance(payload, dict):
            valid = payload.get("validation") or {}
            self.project_label.setText(
                f"工程：{payload.get('name') or '?'} · RTL {len(payload.get('rtl_files') or [])} 个 · "
                f"输入{'齐全' if valid.get('ok') else '不完整'}\n"
                f"目录：{payload.get('root')}")
            self.hint.setText(
                f"rtl_hash：{str(payload.get('rtl_hash'))[:16]}… · "
                f"filelist {len(payload.get('filelist') or [])} 项")
        self.refresh()
        return root

    def _open(self, module_id: str) -> None:
        from ..service.common import open_module
        open_module(self.ctx, module_id)

    def on_summary(self, summary: Dict[str, Any]) -> None:
        doc = (summary or {}).get("manifest") or {}
        reg = doc.get("regression") or {}
        if not doc:
            self.summary_label.setText("还没有 SoC run。点「运行 SoC 回归」或先跑 `soc run`。")
            return
        ev = (summary or {}).get("evidence") or {}
        self.summary_label.setText(
            f"状态：{reg.get('status')} · 通过 {reg.get('passed')}/{reg.get('total')}\n"
            f"波形：{summary.get('wave') or '无'}\n"
            f"证据：{'✓ ' + str(ev.get('files', 0)) + ' 个文件' if ev.get('ok') else '✗ 缺失/不一致'}"
            f" · {summary.get('dir')}")
