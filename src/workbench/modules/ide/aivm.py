"""AIVM 测试点表（xlsx）—— PM/DV lead 手写表的**只读**视图。

方案 B 里 xlsx 是"该测什么"的真源；这一页只读：TP 清单、三通道覆盖点数、
M1 计划摘要、校验统计。导入 casemodel / 防漂移校验在 CLI（`case-model
import-xlsx` / `verify-import`），页面不写盘、不起子进程。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...ui import theme
from ..base import ModuleBase

COLUMNS = ("TP", "分类", "模式", "覆盖点", "配置枚举", "定向用例")


class AivmTableModule(ModuleBase):
    HINT = ("PM/DV lead 手写的测试点表（xlsx）。只读查看 TP 与三通道覆盖点；"
            "导入 casemodel 用 `vagent case-model import-xlsx`。")

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("测试点表"))
        self.path_edit = QLineEdit(root)
        self.path_edit.setPlaceholderText("选择 .xlsx 测试点表")
        row.addWidget(self.path_edit, 1)
        browse = QPushButton("选择…", root)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        refresh = QPushButton("刷新", root)
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)

        self.summary = QLabel("", root)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, len(COLUMNS), root)
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        data_path = self.ctx.data_path(self.spec)
        if data_path is not None and data_path.exists():
            self.path_edit.setText(str(data_path))
        self.refresh()
        return root

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.content, "选择测试点表", "",
            "Excel 测试点表 (*.xlsx *.xlsm);;所有文件 (*)")
        if path:
            self.path_edit.setText(path)
            self.refresh()

    def refresh(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            self.summary.setText("先选择一份 xlsx 测试点表（或用清单里的 input）")
            self.table.setRowCount(0)
            self.set_status("测试点表：未选择文件")
            return
        payload = self.run_tool("humanview.aivm_plan", path=path)
        if not isinstance(payload, dict) or not payload.get("available"):
            error = payload.get("error") if isinstance(payload, dict) else "调用失败"
            self.summary.setText(f"读不了：{error}")
            self.summary.setStyleSheet(f"color: {theme.current().warning};")
            self.table.setRowCount(0)
            return
        rows = payload.get("tps") or []
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = (row.get("orig_id") or row.get("tp_id") or "",
                      row.get("category") or "",
                      row.get("mode") or "",
                      row.get("cover_bins", 0),
                      row.get("config_enums", 0),
                      row.get("directed_cases", 0))
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        self.summary.setStyleSheet(f"color: {theme.current().muted};")
        self.summary.setText(self._summary_text(payload))
        self.set_status(f"测试点表：{len(rows)} 个 TP")

    @staticmethod
    def _summary_text(payload: dict) -> str:
        plan = payload.get("plan") or {}
        totals = plan.get("totals") or {}
        validate = payload.get("validate") or {}
        by_category = "、".join(f"{k}={v}" for k, v in
                                sorted((payload.get("by_category") or {}).items()))
        by_mode = "、".join(f"{k}={v}" for k, v in
                            sorted((payload.get("by_mode") or {}).items()))
        plan_line = (f"计划：cover_bins={totals.get('cover_bins', 0)}"
                     f" config_enums={totals.get('config_enums', 0)}"
                     f" directed={totals.get('directed_cases', 0)}"
                     if plan.get("available") else
                     f"计划：不可用（{plan.get('error') or '校验未通过'}）")
        return (f"{payload.get('tp_count', 0)} 个 TP · {by_category}\n"
                f"模式：{by_mode}\n"
                f"{plan_line}\n"
                f"校验：error={validate.get('errors', 0)} "
                f"warning={validate.get('warnings', 0)}\n"
                f"{Path(payload.get('path') or '').name}")
