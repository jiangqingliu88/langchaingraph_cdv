"""AIVM 测试点表（xlsx）—— PM/DV lead 手写表的**只读**视图。

方案 B 里 xlsx 是"该测什么"的真源；这一页只读：TP 清单、三通道覆盖点数、
M1 计划摘要、校验统计。导入 casemodel / 防漂移校验在 CLI（`case-model
import-xlsx` / `verify-import`），页面不写盘、不起子进程。

**列名按源表表头走**：`humanview.aivm_plan` 用 `discover_column_headers`
读 xlsx 的第 2 行（headtitle）与第 3 行（中文释义），界面照它出列 ——
换一份表头不同的测试点表，GUI 不用改代码。下方 `COLUMNS` 只是 API 不可用
时的兜底（与本仓库示例表一致）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...ui import theme
from ..base import ModuleBase

#: 表头**逐字对齐**源 xlsx（`NPU_V2.CMDSCHED.testpoint.xlsx`）的第 2 行；
#: D/E 两列在源表里同名（都是 `Sub_Sub_Feature（可选）`），用第 3 行的
#: 「三级分类 / 四级分类」后缀区分 —— 否则界面上两列看不出差别。
COLUMNS = (
    ("seq", "序号", 170),
    ("feature", "Feature 提取·一级分类", 170),
    ("sub_feature", "Sub_Feature（可选）·二级分类", 180),
    ("sub_sub_feature", "Sub_Sub_Feature（可选）·三级分类", 200),
    ("sub_sub_sub_feature", "Sub_Sub_Feature（可选）·四级分类", 200),
    ("test_name", "TestName·用例名", 130),
    ("test_num", "TestNum·test个数", 100),
    ("doc_section", "Doc Section·相关文档", 230),
    ("chapter", "章节·摘取位置", 150),
)


class AivmTableModule(ModuleBase):
    HINT = ("PM/DV lead 手写的测试点表（xlsx）。**列名按源表第 2/3 行表头"
            "动态生成**；只读查看 TP 原文与三通道覆盖点，导入 casemodel 用 "
            "`vagent case-model import-xlsx`。")

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
        self.table.setHorizontalHeaderLabels([label for _key, label, _w in COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, (_key, _label, width) in enumerate(COLUMNS):
            self.table.setColumnWidth(column, width)
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
        # **表头来自源 xlsx**（`payload["columns"]`，由 `discover_column_headers`
        # 读第 2/3 行）。API 没给出时才退回本页的 `COLUMNS` —— 不在这里另推一份。
        columns = payload.get("columns") or [
            {"key": key, "label": label} for key, label, _w in COLUMNS]
        widths = {key: width for key, _label, width in COLUMNS}
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([str(c.get("label") or c.get("key"))
                                              for c in columns])
        for column, item in enumerate(columns):
            self.table.setColumnWidth(column, widths.get(str(item.get("key")), 150))
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            # 列值与源表列一一对应 —— 直接取 API 带出的**源表原文**，
            # 不在这里二次推导（表格是输入表的映射，不是另一个视图）。
            values = tuple(row.get(str(item.get("key")), "") for item in columns)
            for column, value in enumerate(values):
                self.table.setItem(index, column,
                                   QTableWidgetItem("" if value is None
                                                    else str(value)))
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
