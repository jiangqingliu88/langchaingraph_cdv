"""SoC C 用例 —— E203 bare-metal C 驱动 IP 的清单 / 运行 / 波形。

和「SoC 验证工作区」的分工：那边看 `regression.yaml` 的用例表（含
`gemm_8x8_c`）并跑整轮回归；这里单独看 `sw/cases.yaml` 的 C 用例、
按用例编译运行、打开对应 qwave.db。数据仍走 `soc.c_cases` / `soc.c_run`。
"""
from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ...ui import theme
from .common import SocModuleBase


class SoCCasesModule(SocModuleBase):
    HINT = ("E203 CPU 执行 bare-metal C，经 NICE custom3 驱动 NPU/DMA/SRAM；"
            "判据是 E203 tb_top 的 TEST_PASS，波形走 qwave.db。")

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addWidget(self._run_bar(root))
        self.run_label = QLabel("尚未选择 run", root)
        self.run_label.setWordWrap(True)
        layout.addWidget(self.run_label)

        row = QHBoxLayout()
        row.addWidget(self._button("运行选中用例", self.run_selected, root))
        row.addWidget(self._button("打开波形", self.open_wave, root))
        row.addWidget(self._button("刷新用例", self.reload_cases, root))
        row.addWidget(self._button("运行历史",
                                   lambda: self._open("flow.runs"), root))
        row.addStretch(1)
        layout.addLayout(row)

        self.hint = QLabel("", root)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.hint)

        self.table = QTableWidget(0, 4, root)
        self.table.setHorizontalHeaderLabels(["用例", "名称", "源码", "IP"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self._cases: List[Dict[str, Any]] = []
        self.reload_cases()
        self.refresh()
        return root

    def _open(self, module_id: str) -> None:
        from ..service.common import open_module
        open_module(self.ctx, module_id)

    def reload_cases(self) -> None:
        payload = self.run_tool("soc.c_cases", quiet=True,
                                project_root=str(self.project_root))
        self._cases = payload if isinstance(payload, list) else []
        self.table.setRowCount(len(self._cases))
        for row, case in enumerate(self._cases):
            values = (case.get("id") or "", case.get("name") or "",
                      case.get("source") or "",
                      "、".join(case.get("ips") or []))
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        if self.table.rowCount():
            self.table.selectRow(0)
        self.hint.setText(
            f"C 用例 {len(self._cases)} 条 · 工程 {self.project_root}\n"
            "需要 RISC-V 工具链；编译会跑 sw/build_sw.py，仿真会生成 "
            "e203/waves/*.db。")

    def _selected_case(self) -> str:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._cases):
            return ""
        return str(self._cases[row].get("id") or "")

    def run_selected(self) -> None:
        case_id = self._selected_case()
        if not case_id:
            self.show_warning("先在表里选一条 C 用例")
            return
        self.show_info(f"编译并运行 C 用例 {case_id}（E203 + NICE + NPU）…")
        result = self.run_tool("soc.c_run", force=True,
                               project_project_root=str(self.project_root),
                               case_id=case_id)
        if isinstance(result, dict):
            if result.get("status") == "PASS":
                wave = ((result.get("sim") or {}).get("wave") or "")
                self.show_info(f"C 用例 {case_id} PASS · {result.get('output_root')}"
                               + (f"\n波形：{wave}" if wave else ""))
            else:
                self.show_error(f"C 用例失败："
                                f"{result.get('error') or result.get('stage')}")
        # 新 run 已落 c_run.json；刷新后 run 选择器会把它列出来（最新在最前）。
        self.refresh()

    def on_summary(self, summary: Dict[str, Any]) -> None:
        doc = (summary or {}).get("manifest") or {}
        reg = doc.get("regression") or {}
        if not doc:
            self.run_label.setText("还没有可选 run。点「运行选中用例」或先跑 "
                                   "`soc c-run`。")
            return
        kind = str((summary or {}).get("kind") or doc.get("kind") or "soc")
        if kind == "soc_c":
            case = doc.get("case") or {}
            self.run_label.setText(
                f"C 用例 {case.get('id') or '?'} · {reg.get('status') or '?'}\n"
                f"波形：{summary.get('wave') or '无'}\n"
                f"{summary.get('dir')}")
        else:
            self.run_label.setText(
                f"SoC 回归 · {reg.get('status') or '?'} · "
                f"通过 {reg.get('passed')}/{reg.get('total')}\n"
                f"波形：{summary.get('wave') or '无'}")
