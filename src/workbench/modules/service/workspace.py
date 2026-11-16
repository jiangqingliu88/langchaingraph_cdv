"""工程目录 / 产物工作区 —— ChipStack 五层架构的界面落点。

这一页只做三件事：

1. **看得见**：L0–L5 每一层在哪、是否存在；L2 的输入目录、L4 的运行与
   agent 产物目录都在树上。
2. **判得了**：按 `CS-DIR-REQ-001 §7` 的验收清单逐条给 PASS/WARN/FAIL，
   失败项直接说缺什么，而不是一句「目录不完整」。
3. **点得动**：初始化工程目录、新建 run、打开产物根 / run / agent 目录。

判定与落盘都在 `runtime_plane.artifacts.project_layout` 里，模块只读结果、
只触发动作 —— 与工作台其它模块同一条边界。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.runtime_plane.artifacts.project_layout import ProjectLayout, RunLayout

from ..base import ModuleBase

_CHECK_COLUMNS = ("需求", "检查项", "状态", "详情")
_RUN_COLUMNS = ("run_id", "状态", "top", "entrypoint", "开始时间", "目录")
_AGENT_COLUMNS = ("Domain", "Agent", "产物目录", "存在", "状态")

_STATUS_COLOR = {
    "PASS": "#2e7d32",
    "WARN": "#b26a00",
    "FAIL": "#c62828",
}


class ProjectWorkspaceModule(ModuleBase):
    HINT = ("ChipStack 五层目录：输入 / 配置 / 产物 / 归档 / 工作流。"
            "产物根可整目录删除，仅凭输入与配置即可重跑。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self._layout: ProjectLayout = ProjectLayout.discover(Path.cwd())
        self._runs: List[Dict[str, Any]] = []
        self._selected_run = ""

    # ══════════════════════════════════════════════════════════
    # 界面
    # ══════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        head = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-weight: bold;")
        head.addWidget(self.summary, 1)
        layout.addLayout(head)

        actions = QHBoxLayout()
        actions.addWidget(_button("刷新", self._reload))
        actions.addWidget(_button("初始化工程目录", self._scaffold))
        actions.addWidget(_button("新建运行", self._new_run))
        actions.addWidget(_button("打开产物根", self._open_artifact_root))
        actions.addWidget(_button("复制检查结果", self._copy_checks))
        actions.addStretch(1)
        layout.addLayout(actions)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_tree())
        splitter.addWidget(self._build_tabs())
        splitter.setSizes([420, 760])
        layout.addWidget(splitter, 1)

        self.note = QLabel("产物约定：修改 RTL 的流程必须留下 backup/；"
                           "归档命名为 <design>.<agent>.<timestamp>。")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #6b6b6b;")
        layout.addWidget(self.note)

        self._reload()
        return root

    def _build_tree(self) -> QWidget:
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(QLabel("L0–L5 目录"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["层 / 目录", "状态"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.itemDoubleClicked.connect(self._open_tree_item)
        outer.addWidget(self.tree, 1)
        return box

    def _build_tabs(self) -> QWidget:
        tabs = QTabWidget()

        self.check_table = _table(_CHECK_COLUMNS)
        tabs.addTab(self.check_table, "验收清单")

        self.run_table = _table(_RUN_COLUMNS)
        self.run_table.itemDoubleClicked.connect(self._open_run_row)
        tabs.addTab(self.run_table, "运行索引")

        self.agent_table = _table(_AGENT_COLUMNS)
        self.agent_table.itemDoubleClicked.connect(self._open_agent_row)
        tabs.addTab(self.agent_table, "Agent 产物")
        return tabs

    # ══════════════════════════════════════════════════════════
    # 刷新
    # ══════════════════════════════════════════════════════════

    def _reload(self) -> None:
        self._layout = ProjectLayout.discover(Path.cwd())
        self._fill_summary()
        self._fill_tree()
        self._fill_checks()
        self._fill_runs()
        self._fill_agents()
        self.set_status(f"工程目录：{self._layout.design_root}")

    def _fill_summary(self) -> None:
        layout = self._layout
        runs = layout.list_runs()
        checks = layout.audit()
        failures = sum(1 for row in checks if row["status"] == "FAIL")
        warnings = sum(1 for row in checks if row["status"] == "WARN")
        state = "未初始化" if not layout.cli_config_path.exists() else "已初始化"
        self.summary.setText(
            f"DESIGN_ROOT：{layout.design_root}　·　{state}\n"
            f"ARTIFACT_ROOT：{layout.artifact_root}\n"
            f"运行 {len(runs)} 个　·　验收 FAIL {failures} / WARN {warnings}"
            f"　·　顶层 module：{layout.top_module or '未配置'}")
        if failures:
            self.show_warning(f"目录验收有 {failures} 项 FAIL —— 切到「验收清单」看缺什么。")
        else:
            self.clear_banner()

    def _fill_tree(self) -> None:
        self.tree.clear()
        for layer in self._layout.layers():
            item = QTreeWidgetItem([f"{layer.id}  {layer.title}",
                                    "存在" if layer.exists else "缺失"])
            item.setToolTip(0, f"{layer.description}\n{layer.path}")
            item.setToolTip(1, str(layer.path))
            item.setData(0, Qt.ItemDataRole.UserRole, str(layer.path))
            self.tree.addTopLevelItem(item)
            if not layer.exists:
                item.setForeground(1, Qt.GlobalColor.gray)
                continue
            if layer.id == "L2":
                for name in ("spec", "rtl", "tb", "ecn", "ref", "scripts", "docs"):
                    path = layer.path / name
                    child = QTreeWidgetItem([f"{name}/", "存在" if path.is_dir() else "缺失"])
                    child.setData(0, Qt.ItemDataRole.UserRole, str(path))
                    child.setToolTip(0, str(path))
                    item.addChild(child)
            elif layer.id == "L4":
                for child_path in _artifact_children(layer.path):
                    child = QTreeWidgetItem([child_path.name + ("/" if child_path.is_dir() else ""), ""])
                    child.setData(0, Qt.ItemDataRole.UserRole, str(child_path))
                    child.setToolTip(0, str(child_path))
                    item.addChild(child)
            elif layer.id == "L5":
                for flow in sorted(p for p in layer.path.iterdir() if p.is_dir()):
                    child = QTreeWidgetItem([f"{flow.name}/", ""])
                    child.setData(0, Qt.ItemDataRole.UserRole, str(flow))
                    item.addChild(child)
        self.tree.expandToDepth(1)

    def _fill_checks(self) -> None:
        checks = self._layout.audit()
        _fill_table(self.check_table, checks, (
            ("id", ""), ("requirement", ""), ("status", ""), ("detail", ""),
        ))
        for row, check in enumerate(checks):
            color = _STATUS_COLOR.get(check["status"], "")
            item = self.check_table.item(row, 2)
            if item is not None and color:
                from PySide6.QtGui import QBrush

                item.setForeground(QBrush(QColor(color)))
                item.setToolTip(check["detail"])

    def _fill_runs(self) -> None:
        self._runs = self._layout.list_runs()
        _fill_table(self.run_table, self._runs, (
            ("run_id", "run_id"), ("status", "status"), ("top_module", "top"),
            ("entrypoint", "entrypoint"), ("started_at", "started_at"),
            ("run_dir", "run_dir"),
        ))
        for row, run in enumerate(self._runs):
            self.run_table.item(row, 5).setData(
                Qt.ItemDataRole.UserRole, str(run.get("run_dir") or ""))

    def _fill_agents(self) -> None:
        from src.agent_plane.domains import all_domains, layout_rows

        run = self._current_run()
        rows: List[Dict[str, Any]] = []
        by_id = {str(row.get("agent_id")): row for row in layout_rows(run)}
        for domain in all_domains():
            for spec in domain.specs():
                row = dict(by_id.get(spec.agent_id, {}))
                row.setdefault("domain", domain.id)
                rows.append(row)
        _fill_table(self.agent_table, rows, (
            ("domain", "Domain"), ("agent_id", "Agent"),
            ("artifact_dir", "产物目录"), ("exists", "存在"), ("status", "状态"),
        ))
        for row, data in enumerate(rows):
            exists = self.agent_table.item(row, 3)
            if exists is not None:
                exists.setText("是" if data.get("exists") else "否")
            self.agent_table.item(row, 2).setData(
                Qt.ItemDataRole.UserRole, str(data.get("path") or ""))

    def _current_run(self) -> RunLayout | None:
        if not self._runs:
            return None
        row = self._runs[-1]
        return self._layout.open_run(
            str(row.get("run_id") or ""), row.get("top_module"),
            scope=str(row.get("scope") or "run"))

    # ══════════════════════════════════════════════════════════
    # 动作
    # ══════════════════════════════════════════════════════════

    def _scaffold(self) -> None:
        target = self._layout.design_root
        if self._layout.cli_config_path.exists():
            answer = QMessageBox.question(
                self.content, "工程已初始化",
                f"{target} 已有 cli_config.yaml。\n继续只会补齐缺失目录与文件，"
                "不会覆盖已有输入。继续？")
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self._layout = self._layout.scaffold(
                name=target.name, top=self._layout.top_module or target.name)
        except Exception as exc:  # noqa: BLE001 —— 界面入口不能穿异常
            self.show_error(f"初始化失败：{exc}")
            return
        self.show_info(f"工程目录已就绪：{self._layout.design_root}")
        self._reload()

    def _new_run(self) -> None:
        default_top = self._layout.top_module or self._layout.design_root.name
        top, ok = QInputDialog.getText(self.content, "新建运行", "顶层 module：", text=default_top)
        if not ok or not top.strip():
            return
        try:
            run = self._layout.create_run(top.strip())
            run.begin(entrypoint="workbench.project.workspace")
            run.log_cli(["workbench", "new-run", top.strip()],
                        note="由工程目录模块创建")
        except Exception as exc:  # noqa: BLE001
            self.show_error(f"新建运行失败：{exc}")
            return
        self.show_info(f"run 已创建：{run.root}")
        self._reload()

    def _open_artifact_root(self) -> None:
        path = self._layout.artifact_root
        if not path.exists():
            self.show_warning(f"产物根还不存在：{path}")
            return
        _open_path(path)

    def _copy_checks(self) -> None:
        rows = self._layout.audit()
        text = "\n".join(
            f"{row['id']}\t{row['requirement']}\t{row['status']}\t{row['detail']}"
            for row in rows)
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self.set_status("验收结果已复制到剪贴板")

    def _open_tree_item(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            _open_path(Path(path))

    def _open_run_row(self, item: QTableWidgetItem) -> None:
        path = self.run_table.item(item.row(), 5).data(Qt.ItemDataRole.UserRole)
        if path and Path(path).is_dir():
            _open_path(Path(path))

    def _open_agent_row(self, item: QTableWidgetItem) -> None:
        path = self.agent_table.item(item.row(), 2).data(Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            _open_path(Path(path))
        else:
            self.show_warning("这个 agent 还没有产物目录（未运行或未登记）。")

    def on_refresh(self, payload: Any = None) -> None:
        self._reload()


# ══════════════════════════════════════════════════════════════
# 小部件
# ══════════════════════════════════════════════════════════════

def _table(columns) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill_table(table: QTableWidget, rows: List[Dict[str, Any]], keys) -> None:
    table.setRowCount(len(rows))
    for row, data in enumerate(rows):
        for col, (key, label) in enumerate(keys):
            value = data.get(key, data.get(label, ""))
            item = QTableWidgetItem("是" if value is True else ("否" if value is False else str(value or "")))
            item.setToolTip(item.text())
            table.setItem(row, col, item)


def _button(text: str, slot) -> QPushButton:
    button = QPushButton(text)
    button.clicked.connect(slot)
    return button


def _open_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _artifact_children(path: Path) -> List[Path]:
    try:
        return sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))[:40]
    except OSError:
        return []
