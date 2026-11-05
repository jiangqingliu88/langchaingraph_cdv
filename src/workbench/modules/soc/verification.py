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
        row.addWidget(self._button("运行 C 用例", self.run_c_case, root))
        row.addWidget(self._button("打开波形", self.open_wave, root))
        row.addWidget(self._button("校验证据包", self.verify_evidence, root))
        row.addWidget(self._button("打开验证流程",
                                   lambda: self._open("flow.pipeline"), root))
        row.addStretch(1)
        layout.addLayout(row)

        self.c_label = QLabel("C 用例：读取中…", root)
        self.c_label.setWordWrap(True)
        self.c_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.c_label)

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
        cases = self.run_tool("soc.c_cases", quiet=True,
                              root=str(self.project_root))
        self._c_cases = cases if isinstance(cases, list) else []
        self.c_label.setText(
            "C 用例：" + ("、".join(str(c.get("id")) for c in self._c_cases)
                          if self._c_cases else "无（sw/cases.yaml 未登记）"))
        self.refresh()
        return root

    def run_c_case(self) -> None:
        if not self._c_cases:
            self.show_warning("没有登记 C 用例（sw/cases.yaml）")
            return
        case_id = str(self._c_cases[0].get("id") or "")
        self.show_info(f"编译并运行 C 用例 {case_id}（E203 + NICE + NPU）…")
        result = self.run_tool("soc.c_run", force=True,
                               project_root=str(self.project_root),
                               case_id=case_id)
        if isinstance(result, dict):
            if result.get("status") == "PASS":
                self.show_info(f"C 用例 PASS · {result.get('output_root')}")
            else:
                self.show_error(f"C 用例失败：{result.get('error') or result.get('stage')}")
        # c_run.json 已落盘；刷新 run 选择器（含运行历史）让它可见。
        self.refresh()

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
        kind = str((summary or {}).get("kind") or doc.get("kind") or "soc")
        if kind == "soc_c":
            case = doc.get("case") or {}
            self.status.setText(
                f"C 用例 {case.get('id') or '?'} · {reg.get('status') or '?'}\n"
                f"波形：{summary.get('wave') or '无'}")
            return
        self.status.setText(
            f"{reg.get('status')} · 通过 {reg.get('passed')}/{reg.get('total')} · "
            f"失败 {reg.get('failed')} · 未知 {reg.get('unknown')}\n"
            f"波形：{summary.get('wave') or '无'}")
