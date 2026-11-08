"""**VPlan 项目** —— GUI 里的 VPlan 产物视图（只读）。

取代已删除的「Case 建模」页：VPlan 是唯一输入，页面回答三件事：

  · 项目侧 —— 需求 / feature / 专题 / 契约 / TP / case 的计数与状态
  · 运行侧 —— 选中的 run 产出了什么（TP IR / 覆盖率计划 / 契约 / sv 资产 / 回归）
  · 文件侧 —— 这些产物在盘上的位置与大小（缺了要能看见，不编造）

数据只来自 `vplan.status` / `vplan.run_artifacts`（`vplan/report.py`），
本页不解析 CSV、不重跑生成器。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.workbench.bus import run_id_of

from ...base import ModuleBase


class VPlanModule(ModuleBase):
    HINT = "VPlan 项目 + 运行产物：契约 / TP / case / 覆盖率计划 / sv 资产。"

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id = ""
        self.run_dir = ""
        initial = self.ctx.data_path(spec) if self.ctx else None
        self._project = str(initial) if initial else ""

    # ── 界面 ──────────────────────────────────────────────

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        self.project_edit = QLineEdit(root)
        self.project_edit.setPlaceholderText("VPlan 项目根（含 data/*.csv 与 cases/*.yaml）")
        self.project_edit.setText(self._project)
        row.addWidget(self.project_edit, 1)
        load_btn = QPushButton("读取项目", root)
        load_btn.clicked.connect(self._load_project)
        row.addWidget(load_btn)
        layout.addLayout(row)

        self.summary = QLabel("", root)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        layout.addWidget(QLabel("项目状态", root))
        self.status_table = self._table(
            ("对象", "数量", "状态分布"), root)
        layout.addWidget(self.status_table, 1)

        layout.addWidget(QLabel("运行产物", root))
        self.artifact_table = self._table(
            ("产物", "路径", "在? ", "大小"), root)
        layout.addWidget(self.artifact_table, 1)

        self.notes = QLabel("", root)
        self.notes.setWordWrap(True)
        layout.addWidget(self.notes)

        if self._project:
            self._load_project()
        return root

    @staticmethod
    def _table(headers, parent) -> QTableWidget:
        table = QTableWidget(0, len(headers), parent)
        table.setHorizontalHeaderLabels(list(headers))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    # ── 数据 ──────────────────────────────────────────────

    def _load_project(self) -> None:
        path = self.project_edit.text().strip()
        if not path:
            self.show_info("先给一个 VPlan 项目目录。")
            return
        payload = self.run_tool("vplan.status", project_root=path)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            return
        self._fill_project(payload)

    def _fill_project(self, payload: Dict[str, Any]) -> None:
        self.summary.setText(
            f"{payload.get('module', '')} · DUT={payload.get('dut', '')} · "
            f"spec={str(payload.get('spec_hash') or '')[:12]}　"
            f"需求 {payload.get('requirements', 0)} / feature {payload.get('features', 0)} / "
            f"专题 {payload.get('topics', 0)}")
        rows = [
            ("契约", payload.get("contracts", 0),
             payload.get("contracts_by_status") or {}),
            ("测试点", payload.get("testpoints", 0),
             payload.get("testpoints_by_status") or {}),
            ("case", payload.get("cases", 0),
             payload.get("cases_by_status") or {}),
        ]
        self.status_table.setRowCount(len(rows))
        for r, (name, count, by) in enumerate(rows):
            for c, value in enumerate(
                    (name, count, "、".join(f"{k}={v}" for k, v in sorted(by.items())))):
                self.status_table.setItem(r, c, QTableWidgetItem(str(value)))
        self.notes.setText(
            f"{payload.get('status', '')} · signable={payload.get('signable', False)}　"
            + "　".join(payload.get("warnings") or []))

    def _fill_run(self, payload: Dict[str, Any]) -> None:
        self.summary.setText(
            f"运行 {payload.get('run_id', '')}：TP {payload.get('testpoints', 0)} / "
            f"批次 {payload.get('batches', 0)} / 覆盖点 {payload.get('coverpoints', 0)}　"
            f"契约 {payload.get('contract_id', '')}（义务 {payload.get('obligations', 0)}）"
            f" · 映射 {payload.get('mapped_contracts', 0)} 条 C-*")
        artifacts = list(payload.get("artifacts") or [])
        self.artifact_table.setRowCount(len(artifacts))
        for r, item in enumerate(artifacts):
            values = (item.get("label", ""), item.get("path", ""),
                      "✓" if item.get("exists") else "✗", item.get("size", 0))
            for c, value in enumerate(values):
                self.artifact_table.setItem(r, c, QTableWidgetItem(str(value)))
        self.notes.setText(
            f"sv 资产 {payload.get('sv_assets', 0)} · "
            f"回归 {payload.get('regression') or '—'} · "
            f"签核 {payload.get('signoff') or '—'}")

    def on_refresh(self, payload: Any = None) -> None:
        run_id = run_id_of(payload)
        if run_id and run_id != self.run_id:
            self.load(run_id)

    def load(self, run_id: str) -> None:
        if not run_id:
            return
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=run_id)
        if not isinstance(detail, dict) or self.report_payload_error(detail):
            return
        self.run_id = run_id
        self.run_dir = str(detail.get("dir", "") or "")
        if not self.run_dir:
            self.show_warning(f"找不到运行 {run_id} 的目录")
            return
        payload = self.run_tool("vplan.run_artifacts", run_dir=self.run_dir)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            return
        self._fill_run(payload)
        root = str(payload.get("project") or "")
        if root:
            self.project_edit.setText(root)
            self._load_project()
