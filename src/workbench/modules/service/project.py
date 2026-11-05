"""项目总览 / 项目管理 —— 客户视角的两页入口。

总览回答「当前项目到哪了、结果如何、交付物在哪」；管理页列出登记过的项目并
说明切换需要重启。两页都只读，不执行流水线、不产生签核结论。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..base import ModuleBase
from .common import load_runs, open_module, publish_run, selected_run

_PROJECT_COLUMNS = ("id", "名称", "工作目录", "存在")


class ProjectOverviewModule(ModuleBase):
    HINT = "当前项目与最近一次运行的进展、覆盖率、签核与证据入口。"

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self._runs = []
        self._selected = ""

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)

        self.project_label = QLabel(_project_line())
        layout.addWidget(self.project_label)

        row = QHBoxLayout()
        self.run_combo = QComboBox()
        self.run_combo.setMinimumWidth(320)
        self.run_combo.currentIndexChanged.connect(self._run_changed)
        row.addWidget(QLabel("运行"))
        row.addWidget(self.run_combo, 1)
        row.addWidget(_button("刷新", self._reload_runs))
        layout.addLayout(row)

        self.summary = QLabel("尚未选择运行")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        row2 = QHBoxLayout()
        row2.addWidget(_button("SoC 参考工程", lambda: open_module(self.ctx, "soc.overview")))
        row2.addWidget(_button("UVM 自动化验证", lambda: open_module(self.ctx, "service.uvm")))
        row2.addWidget(_button("回归效率优化", lambda: open_module(self.ctx, "service.regression")))
        row2.addWidget(_button("Coverage Closure", lambda: open_module(self.ctx, "service.coverage")))
        row2.addStretch(1)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(_button("运行历史", lambda: open_module(self.ctx, "flow.runs")))
        row3.addWidget(_button("证据 / 产物", lambda: open_module(self.ctx, "flow.evidence")))
        row3.addWidget(_button("签核判定", lambda: open_module(self.ctx, "flow.signoff")))
        row3.addWidget(_button("运行对比", lambda: open_module(self.ctx, "flow.compare")))
        row3.addStretch(1)
        layout.addLayout(row3)
        layout.addStretch(1)

        self._reload_runs()
        return root

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
            self.summary.setText("还没有运行。从「工程服务」启动一次验证。")

    def _run_changed(self, index: int) -> None:
        run = self._current_run()
        run_id = str((run or {}).get("run_id") or "")
        if not run_id:
            return
        self._selected = run_id
        publish_run(self.ctx, run_id)
        verdict = run.get("verdict") or "-"
        status = run.get("signoff_status") or "-"
        state = run.get("state") or ("finished" if run.get("finished") else "unknown")
        self.summary.setText(
            f"运行：{run_id}\n"
            f"状态：{state} · 当前阶段：{run.get('current_stage') or '-'}"
            f" · 轮次：{run.get('round', 0)}\n"
            f"覆盖率：{run.get('final_coverage', 0)}% / 目标 {run.get('target', 95)}%"
            f" · 收敛：{'是' if run.get('converged') else '否'}\n"
            f"签核：{verdict} / {status}"
            f" · 证据链：{'有效' if run.get('evidence_valid') else '未校验/无效'}\n"
            f"目录：{run.get('dir', '')}")
        self.set_status(f"项目总览：{run_id}")

    def _current_run(self):
        run_id = str(self.run_combo.currentData() or "")
        for run in self._runs:
            if str(run.get("run_id") or "") == run_id:
                return run
        return None

    def on_refresh(self, payload=None) -> None:
        run_id = selected_run(payload)
        if run_id:
            index = self.run_combo.findData(run_id)
            if index >= 0:
                self.run_combo.setCurrentIndex(index)


class ProjectManagementModule(ModuleBase):
    HINT = "登记过的项目；切换项目需要重启工作台（--project <id>）。"

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        form = QFormLayout()
        form.addRow("当前工作目录", _selectable(str(Path.cwd())))
        form.addRow("当前项目", _selectable(_project_line()))
        form.addRow("界面清单", _selectable(str(self.ctx.manifest_path)))
        layout.addLayout(form)

        layout.addWidget(QLabel("登记表：~/.signoffai/projects.yaml"
                                "（可用 SIGNOFFAI_PROJECTS 覆盖）"))
        self.table = QTableWidget(0, len(_PROJECT_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_PROJECT_COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.addWidget(_button("刷新", self._reload))
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(_muted("切换项目：重启工作台并加 `--project <id>`。"
                                "热切换会留下旧 cwd 的单例句柄，所以不在这里做。"))
        self._reload()
        return root

    def _reload(self) -> None:
        from ...projects import current, load_projects
        projects = load_projects()
        self.table.setRowCount(len(projects))
        for row, project in enumerate(projects):
            values = (project.id, project.name, project.root,
                      "是" if project.exists else "否")
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.set_status(f"项目登记表：{len(projects)} 条"
                        + (f" · 当前 {current().id}" if current() else ""))


def _project_line() -> str:
    try:
        from ...projects import current
        project = current()
        return f"{project.name}（{project.id}）" if project else "未登记（按工作目录运行）"
    except Exception:                       # noqa: BLE001
        return "未登记"


def _button(text: str, slot) -> QPushButton:
    button = QPushButton(text)
    button.clicked.connect(slot)
    return button


def _selectable(text: str) -> QLabel:
    from PySide6.QtCore import Qt
    label = QLabel(text)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #6b6b6b;")
    return label
