"""Coverage Closure 服务入口。

读已有 run 的覆盖率数据生成缺口/动作计划；执行仍由现有闭环（CLI
`coverage-closure --execute`）承担。GUI 明确区分：豁免、达到目标、真正收敛
是三个不同结论。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..base import ModuleBase
from .common import load_runs, open_module, publish_run, run_dir, selected_run

_COLUMNS = ("TP", "coverpoint", "bin", "状态", "动作", "优先级")


class CoverageClosureModule(ModuleBase):
    HINT = "缺口 → 定向动作计划；豁免 / 达标 / 收敛是三个不同结论。"

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self._runs = []
        self._plan = None
        self._selected = ""

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(QLabel("选择一次已有运行，读取它的覆盖率缺口并生成 Closure 计划。"
                                "本页只读计划，不在这里跑仿真。"))
        row = QHBoxLayout()
        self.run_combo = QComboBox()
        self.run_combo.setMinimumWidth(320)
        self.run_combo.currentIndexChanged.connect(self._run_changed)
        row.addWidget(QLabel("运行"))
        row.addWidget(self.run_combo, 1)
        row.addWidget(_button("刷新", self._reload_runs))
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(0.0, 100.0)
        self.target_spin.setValue(98.0)
        self.target_spin.setSuffix(" %")
        row2.addWidget(QLabel("目标覆盖率"))
        row2.addWidget(self.target_spin)
        self.plan_btn = QPushButton("生成 Closure 计划")
        self.plan_btn.clicked.connect(self._make_plan)
        row2.addWidget(self.plan_btn)
        row2.addWidget(_button("打开运行历史", lambda: open_module(self.ctx, "flow.runs")))
        row2.addStretch(1)
        layout.addLayout(row2)

        self.summary = QLabel("尚未生成计划")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        row3 = QHBoxLayout()
        row3.addWidget(_button("回归覆盖率", lambda: open_module(self.ctx, "ops.regression_coverage")))
        row3.addWidget(_button("覆盖率豁免", lambda: open_module(self.ctx, "coverage.excludes")))
        row3.addWidget(_button("产物审查", lambda: open_module(self.ctx, "flow.artifacts")))
        row3.addWidget(_button("证据", lambda: open_module(self.ctx, "flow.evidence")))
        row3.addWidget(_button("签核判定", lambda: open_module(self.ctx, "flow.signoff")))
        row3.addStretch(1)
        layout.addLayout(row3)
        layout.addWidget(_muted("执行收敛：vagent coverage-closure --coverage <run> "
                                "--target <N> --execute"))

        self._reload_runs()
        return root

    # ── 运行选择 ──

    def _reload_runs(self) -> None:
        current = self._selected or self.run_combo.currentData()
        self._runs = load_runs(self.ctx)
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        for run in self._runs:
            run_id = str(run.get("run_id") or "")
            if run_id:
                self.run_combo.addItem(run_id, run_id)
        if current:
            index = self.run_combo.findData(current)
            if index >= 0:
                self.run_combo.setCurrentIndex(index)
        self.run_combo.blockSignals(False)
        if self._runs:
            self._run_changed(self.run_combo.currentIndex())
        else:
            self.summary.setText("没有可用的运行（先跑一次验证）")

    def _run_changed(self, index: int) -> None:
        run_id = str(self.run_combo.currentData() or "")
        self._selected = run_id
        if run_id:
            publish_run(self.ctx, run_id)
            self.set_status(f"Coverage Closure：当前运行 {run_id}")

    def _current_run(self):
        run_id = str(self.run_combo.currentData() or "")
        for run in self._runs:
            if str(run.get("run_id") or "") == run_id:
                return run
        return None

    # ── 计划 ──

    def _make_plan(self) -> None:
        from src.runtime_plane.core.closure.plan import write_closure_plan

        run = self._current_run()
        path = run_dir(run) if run else None
        if path is None:
            self.show_warning("请选择有目录的运行")
            return
        plan = write_closure_plan(path, float(self.target_spin.value()))
        self._plan = plan
        self.summary.setText(
            f"当前 {plan['current_coverage']}% / 目标 {plan['target']}%"
            f" · 缺口 {plan['gap_count']} 个 · 差距 {plan['gap_to_target']} 点\n"
            f"计划：{plan.get('path', '')}\n"
            "注意：覆盖率豁免、达到目标、真正收敛是三个不同结论。")
        actions = plan.get("actions") or []
        self.table.setRowCount(len(actions))
        for row, item in enumerate(actions[:200]):
            values = (item.get("tp_id"), item.get("coverpoint"), item.get("bin"),
                      item.get("status"), item.get("action"), item.get("priority"))
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value or "")))
        self.show_info("Closure 计划已生成（未执行仿真）")

    def on_refresh(self, payload=None) -> None:
        run_id = selected_run(payload)
        if not run_id:
            return
        index = self.run_combo.findData(run_id)
        if index >= 0:
            self.run_combo.setCurrentIndex(index)


def _button(text: str, slot) -> QPushButton:
    button = QPushButton(text)
    button.clicked.connect(slot)
    return button


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #6b6b6b;")
    return label
