"""SoC 验证工作区 —— 测试计划 / 回归用例 / 状态入口。"""
from __future__ import annotations

from typing import Any, Dict

from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ...ui import theme
from .common import SocModuleBase


class SoCVerificationModule(SocModuleBase):
    HINT = ("SoC 回归用例与结果；仿真判定仍是日志里的 mismatched=0 / PASS。"
            "波形和证据由 run 选择器联动。")

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addWidget(self._run_bar(root))
        self.status = QLabel("尚未选择 SoC run", root)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        row = QHBoxLayout()
        row.addWidget(self._button("运行 SoC 回归", self.run_soc, root))
        row.addWidget(self._button("打开波形", self.open_wave, root))
        row.addWidget(self._button("校验证据包", self.verify_evidence, root))
        row.addWidget(self._button("打开验证流程",
                                   lambda: self._open("flow.pipeline"), root))
        row.addStretch(1)
        layout.addLayout(row)

        label = QLabel("回归用例（regression/regression.yaml）", root)
        label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(label)
        self.table = QTableWidget(0, 4, root)
        self.table.setHorizontalHeaderLabels(["用例", "build", "tags", "预仿真"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        payload = self.run_tool("soc.project", quiet=True,
                                root=str(self.project_root))
        self._fill_tests(payload if isinstance(payload, dict) else {})
        self.refresh()
        return root

    def _open(self, module_id: str) -> None:
        from ..service.common import open_module
        open_module(self.ctx, module_id)

    def _fill_tests(self, info: Dict[str, Any]) -> None:
        tests = ((info.get("regression") or {}).get("tests") or
                 (info.get("regression") or {}).get("test") or [])
        if isinstance(tests, dict):
            tests = [tests]
        self.table.setRowCount(len(tests))
        for row, test in enumerate(tests):
            if not isinstance(test, dict):
                continue
            values = (test.get("name") or "", test.get("build") or "",
                      "、".join(test.get("tags") or []),
                      "有" if test.get("hooks", {}).get("pre_sim") else "无")
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))

    def on_summary(self, summary: Dict[str, Any]) -> None:
        doc = (summary or {}).get("manifest") or {}
        reg = doc.get("regression") or {}
        if not doc:
            self.status.setText("还没有 SoC run。")
            return
        self.status.setText(
            f"{reg.get('status')} · 通过 {reg.get('passed')}/{reg.get('total')} · "
            f"失败 {reg.get('failed')} · 未知 {reg.get('unknown')}\n"
            f"波形：{summary.get('wave') or '无'}")
