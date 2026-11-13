"""回归效率优化服务入口。

只做**历史分析 + 优化计划 + 导航**：分析用 `src/runtime_plane/core/optimize`，执行仍由
CLI `optimize-regression --execute` 或现有回归执行器承担。GUI 不宣称自己
具备自动调度能力。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..base import ModuleBase
from .common import open_module

_COLUMNS = ("用例", "pass", "fail", "unknown", "平均耗时(s)", "精确 bin")


class RegressionServiceModule(ModuleBase):
    HINT = "历史回归 → flaky/failing/慢用例 → 低边际用例建议；执行走 CLI。"

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self._task_id = ""
        self._plan = None

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(QLabel("选择历史 run 目录并生成优化计划。"
                                "没有精确 per-test 归因时不会建议跳过任何用例。"))
        form = QFormLayout()
        self.project_edit = QLineEdit(".")
        form.addRow("项目目录", self._with_browse(self.project_edit, "dir"))
        self.history_edit = QLineEdit()
        self.history_edit.setPlaceholderText("留空 = 扫项目下的 output_*")
        form.addRow("历史 run 目录", self._with_browse(self.history_edit, "dir"))
        layout.addLayout(form)

        row = QHBoxLayout()
        self.analyze_btn = QPushButton("分析并生成计划")
        self.analyze_btn.clicked.connect(self._analyze)
        row.addWidget(self.analyze_btn)
        row.addWidget(_button("运行历史", lambda: open_module(self.ctx, "flow.runs")))
        row.addWidget(_button("回归状态", lambda: open_module(self.ctx, "ops.regression_status")))
        row.addWidget(_button("运行对比", lambda: open_module(self.ctx, "flow.compare")))
        row.addStretch(1)
        layout.addLayout(row)

        self.summary = QLabel("尚未分析")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        row2 = QHBoxLayout()
        row2.addWidget(_button("仿真日志", lambda: open_module(self.ctx, "debug.sim_log")))
        row2.addWidget(_button("错误指纹", lambda: open_module(self.ctx, "debug.fingerprint")))
        row2.addWidget(_button("进度趋势", lambda: open_module(self.ctx, "flow.trend")))
        row2.addWidget(_button("决策轨迹", lambda: open_module(self.ctx, "flow.decision")))
        row2.addStretch(1)
        layout.addLayout(row2)
        layout.addWidget(_muted("执行优化回归：vagent optimize-regression "
                                "--project <dir> --history <dir> --execute"))

        self.ctx.tasks.finished.connect(self._task_finished)
        self.ctx.tasks.failed.connect(self._task_failed)
        return root

    # ── 分析 ──

    def _analyze(self) -> None:
        if self._task_id:
            self.show_info("上一次分析还在跑")
            return
        project = self.project_edit.text().strip() or "."
        history = self.history_edit.text().strip()
        self.analyze_btn.setEnabled(False)
        self.summary.setText("正在分析历史回归…")
        self._task_id = self.ctx.tasks.submit(
            "回归历史分析", lambda: _analyze_plan(project, history))

    def _task_finished(self, task_id: str, result) -> None:
        if task_id != self._task_id:
            return
        self._task_id = ""
        self.analyze_btn.setEnabled(True)
        if not isinstance(result, dict):
            self.show_error("分析返回了非预期结果")
            return
        self._plan = result.get("plan")
        self._render(result)

    def _task_failed(self, task_id: str, message: str) -> None:
        if task_id != self._task_id:
            return
        self._task_id = ""
        self.analyze_btn.setEnabled(True)
        self.show_error(f"分析失败：{message}")

    def _render(self, result: dict) -> None:
        plan = result.get("plan") or {}
        self.summary.setText(
            f"历史 run {result.get('runs', 0)} 个 / 用例 {plan.get('tests', 0)} 条\n"
            f"flaky {len(plan.get('flaky') or [])} · failing {len(plan.get('failing') or [])}"
            f" · 低边际跳过 {len(plan.get('skipped_tests') or [])}\n"
            f"预计节省 {plan.get('estimated_savings_seconds')}s"
            f"（{plan.get('estimated_savings_pct')}%）· 置信度 {plan.get('confidence')}\n"
            f"计划：{result.get('path', '')}")
        tests = (result.get("report") or {}).get("tests") or {}
        rows = sorted(tests.items(), key=lambda kv: kv[1].get("avg_elapsed") or 0,
                      reverse=True)[:20]
        self.table.setRowCount(len(rows))
        for row, (name, e) in enumerate(rows):
            values = (name, e.get("pass"), e.get("fail"), e.get("unknown"),
                      e.get("avg_elapsed"), len(e.get("bins_exact") or []))
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.show_info("优化计划已生成（未执行回归）")

    # ── 小工具 ──

    def _with_browse(self, edit: QLineEdit, kind: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        row.addWidget(_button("浏览…", lambda: self._browse(edit)))
        return box

    def _browse(self, edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self.content, "选择目录")
        if path:
            edit.setText(path)

    def on_refresh(self, payload=None) -> None:
        from .common import selected_run
        run_id = selected_run(payload)
        if run_id:
            self.set_status(f"回归效率优化：当前运行 {run_id}")


def _analyze_plan(project: str, history: str) -> dict:
    """工作线程里跑的分析：纯读 + 写一份计划，不碰控件、不跑 EDA。"""
    from src.runtime_plane.core.optimize.history import collect_history, find_run_dirs
    from src.runtime_plane.core.optimize.plan import build_plan, write_plan

    runs = find_run_dirs(Path(project), Path(history) if history else None)
    report = collect_history(runs)
    plan = build_plan(report)
    target = runs[-1] if runs else Path(project)
    plan = write_plan(target, plan)
    return {"runs": len(runs), "report": report, "plan": plan,
            "path": plan.get("path", "")}


def _button(text: str, slot) -> QPushButton:
    button = QPushButton(text)
    button.clicked.connect(slot)
    return button


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #6b6b6b;")
    return label
