"""ISA 激励 —— .ir.txt 在界面上编译成 seq.ir 与 commands.tsv。

工具本身在 `src/generation_plane/isa_ir_tools/`：输入一份手写 IR（或已解析
seq.ir），三阶段产出 `01_tensors / 02_ir / 03_commands`。这一页把那条
命令行的“看得见的过程”摆出来：

  · 校验：解析出多少条动作、哪些是指令、哪些是 TB 控制
  · 编译：每条记录最终编成什么 74-bit cmddata / 控制行
  · seq.ir / 日志 / 原始 JSON：出问题时能当场对

界面只经 `bridge/catalog.py` 的绑定访问工具，**不 import 工具包**。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton,
                               QSpinBox, QSplitter, QTabWidget, QVBoxLayout,
                               QWidget)

from ....ui import theme
from ....ui.helpers import tables as table_helpers
from ....ui.models import LEFT, RIGHT, RowsModel
from ...base import ModuleBase

#: 一份最小可编译的示例：一个张量、一个 LMEM 视图、一条控制指令。
SAMPLE = """.case seed=7
.tensor T, shape=[1,1,4], dtype="int8", pattern="ones", region="dram_common", base=0x1000
.bind T_d, tensor="T", region="lmem_core_spad", base=0x100
nop
"""

ACTION_COLUMNS = (
    ("index", "#", 48, RIGHT),
    ("line", "行", 56, RIGHT),
    ("kind", "类型", 64, LEFT),
    ("op", "操作", 190, LEFT),
    ("fields", "字段", 620, LEFT),
)
COMMAND_COLUMNS = (
    ("index", "#", 48, RIGHT),
    ("line", "源行", 56, RIGHT),
    ("kind", "类型", 72, LEFT),
    ("op", "操作", 190, LEFT),
    ("detail", "内容", 620, LEFT),
)

TAB_ACTIONS, TAB_COMMANDS, TAB_SEQ, TAB_LOGS, TAB_RAW = range(5)


class IsaGenModule(ModuleBase):
    """IR → 张量 / seq.ir / 命令流的编译与查看。"""

    HINT = ("写/打开一份 .ir.txt（手写源或已解析 seq.ir）。「校验」只解析不写盘；"
            "「编译并落盘」跑完整三阶段，产物落在你选的目录下。")

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec)
        self.validation: Optional[Dict[str, Any]] = None
        self.build: Optional[Dict[str, Any]] = None
        self.source_path: str = ""

    # ════════════════════════════════════════════════════════
    # 界面
    # ════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_toolbar(root))

        splitter = QSplitter(Qt.Orientation.Vertical, root)
        self.editor = QPlainTextEdit(splitter)
        self.editor.setFont(theme.mono_font())
        self.editor.setPlaceholderText(".case / .tensor / .bind / 指令 / TB 控制")
        self.editor.setPlainText(SAMPLE)
        splitter.addWidget(self.editor)

        self.tabs = QTabWidget(splitter)
        self.tabs.addTab(self._build_table_page(ACTION_COLUMNS, "action"),
                         "动作（校验）")
        self.tabs.addTab(self._build_table_page(COMMAND_COLUMNS, "command"),
                         "命令流")
        self.tabs.addTab(self._build_text_page("seq.ir 预览", "seq_text"), "seq.ir")
        self.tabs.addTab(self._build_text_page("阶段日志", "log_text"), "日志")
        self.tabs.addTab(self._build_text_page("完整 JSON", "raw"), "原始 JSON")
        splitter.addWidget(self.tabs)

        splitter.setSizes([280, 420])
        layout.addWidget(splitter, 1)
        return root

    def _build_toolbar(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(3)

        hint = QLabel(self.HINT, panel)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        outer.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("IR：", panel))
        self.path_edit = QLineEdit(panel)
        self.path_edit.setPlaceholderText("（未打开文件 —— 用下面编辑框里的内容）")
        self.path_edit.setReadOnly(True)
        row.addWidget(self.path_edit, 1)
        self.btn_open = QPushButton("打开…", panel)
        self.btn_open.clicked.connect(self.open_ir)
        row.addWidget(self.btn_open)
        self.btn_sample = QPushButton("填示例", panel)
        self.btn_sample.clicked.connect(lambda: self.editor.setPlainText(SAMPLE))
        row.addWidget(self.btn_sample)
        outer.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_check = QPushButton("校验", panel)
        self.btn_check.clicked.connect(self.check_ir)
        row2.addWidget(self.btn_check)

        self.btn_build = QPushButton("编译并落盘…", panel)
        self.btn_build.setDefault(True)
        self.btn_build.clicked.connect(self.build_ir)
        row2.addWidget(self.btn_build)

        row2.addWidget(QLabel("target：", panel))
        self.target_combo = QComboBox(panel)
        self.target_combo.addItem("standalone")
        row2.addWidget(self.target_combo)

        row2.addWidget(QLabel("core：", panel))
        self.core_spin = QSpinBox(panel)
        self.core_spin.setRange(0, 15)
        self.core_spin.setValue(0)
        row2.addWidget(self.core_spin)

        self.summary = QLabel("还没有校验过。", panel)
        row2.addWidget(self.summary, 1)
        outer.addLayout(row2)
        return panel

    def _build_table_page(self, columns, attr: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        model = RowsModel(columns, page)
        table = table_helpers.configure_table(page, model)
        layout.addWidget(table, 1)
        setattr(self, f"{attr}_model", model)
        return page

    def _build_text_page(self, placeholder: str, attr: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        view = QPlainTextEdit(page)
        view.setReadOnly(True)
        view.setFont(theme.mono_font())
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        view.setPlaceholderText(placeholder)
        layout.addWidget(view, 1)
        setattr(self, attr, view)
        return page

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def create_actions(self) -> List[QAction]:
        check = QAction("校验 ISA IR", self.content)
        check.triggered.connect(self.check_ir)
        build = QAction("编译 ISA IR 并落盘…", self.content)
        build.triggered.connect(self.build_ir)
        return [check, build]

    def on_input_changed(self, path) -> None:
        target = Path(path)
        if not target.is_file():
            return
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.show_error(f"读不了这份 IR：{exc}")
            return
        self.editor.setPlainText(text)
        self.source_path = str(target)
        self.path_edit.setText(str(target))
        self.validation = None
        self.set_status(f"已载入 {target.name}")
        if self._widget is not None:
            self.check_ir()

    def on_activated(self) -> None:
        if self.validation is None and self.editor.toPlainText().strip():
            self.check_ir()

    # ════════════════════════════════════════════════════════
    # 动作
    # ════════════════════════════════════════════════════════

    def open_ir(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self.content, "选择 IR 文件", "",
            "IR (*.ir.txt *.txt);;所有文件 (*)")
        if path:
            self.on_input_changed(path)

    def check_ir(self) -> None:
        text = self.editor.toPlainText()
        if not text.strip():
            self.show_warning("还没有 IR —— 打开一份文件，或用「填示例」。")
            return
        payload = self.run_tool("isa_ir.validate", source_text=text)
        if not isinstance(payload, dict):
            return
        if not payload.get("ok"):
            self.validation = None
            self.action_model.set_rows([])
            self.summary.setText("校验失败。")
            self.show_error(_format_error(payload))
            return
        self.validation = payload
        self._render_validation(payload)

    def build_ir(self) -> None:
        text = self.editor.toPlainText()
        if not text.strip():
            self.show_warning("还没有 IR —— 打开一份文件，或用「填示例」。")
            return
        parent = QFileDialog.getExistingDirectory(self.content, "选择输出目录")
        if not parent:
            return
        bundle = Path(parent) / _case_name(self.source_path)
        payload = self.run_tool("isa_ir.build", force=True, source_text=text,
                                out_dir=str(bundle),
                                target=self.target_combo.currentText(),
                                core_id=self.core_spin.value())
        if not isinstance(payload, dict):
            return
        if not payload.get("ok"):
            self.build = None
            self.log_text.setPlainText(_logs_text(payload))
            self.tabs.setCurrentIndex(TAB_LOGS)
            self.show_error(_format_error(payload))
            return
        self.build = payload
        self._render_build(payload)

    # ════════════════════════════════════════════════════════
    # 渲染
    # ════════════════════════════════════════════════════════

    def _render_validation(self, payload: Dict[str, Any]) -> None:
        rows = []
        for action in payload.get("actions", []):
            rows.append({
                "index": action.get("index", ""),
                "line": action.get("line", ""),
                "kind": "控制" if action.get("kind") == "control" else "指令",
                "op": action.get("op", ""),
                "fields": action.get("fields_text", ""),
            })
        self.action_model.set_rows(rows)
        counts = payload.get("counts", {})
        self.summary.setText(
            f"张量 {counts.get('tensors', 0)} · 视图 {counts.get('views', 0)} · "
            f"动作 {counts.get('actions', 0)}（指令 {counts.get('instructions', 0)} / "
            f"控制 {counts.get('controls', 0)}） · {payload.get('isa_revision', '')}")
        self.raw.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))
        self.set_status("IR 校验通过")
        self.clear_banner()

    def _render_build(self, payload: Dict[str, Any]) -> None:
        commands = (payload.get("commands_json") or {}).get("commands", [])
        rows = []
        for record in commands:
            rows.append({
                "index": record.get("index", ""),
                "line": record.get("source_line", ""),
                "kind": "指令" if record.get("kind") == "instruction" else "控制",
                "op": record.get("op", ""),
                "detail": _record_detail(record),
            })
        self.command_model.set_rows(rows)
        self.seq_text.setPlainText(payload.get("seq_ir", ""))
        self.log_text.setPlainText(_logs_text(payload))
        self.raw.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))
        instructions = sum(1 for row in rows if row["kind"] == "指令")
        self.summary.setText(
            f"已编译 {len(rows)} 条记录（指令 {instructions}） → {payload.get('bundle', '')}")
        self.tabs.setCurrentIndex(TAB_COMMANDS)
        self.set_status("编译完成")
        self.clear_banner()


def _case_name(path: str) -> str:
    name = Path(path).name if path else "isa_ir_case"
    if name.lower().endswith(".ir.txt"):
        name = name[:-7]
    elif name:
        name = Path(name).stem
    return name or "isa_ir_case"


def _record_detail(record: Dict[str, Any]) -> str:
    if record.get("cmddata"):
        return record["cmddata"]
    if record.get("passthrough"):
        return str(record["passthrough"])
    parameters = record.get("parameters")
    return json.dumps(parameters, ensure_ascii=False) if parameters is not None else ""


def _format_error(payload: Dict[str, Any]) -> str:
    error = payload.get("error") or {}
    if isinstance(error, dict):
        line = error.get("line")
        where = f"（第 {line} 行）" if line is not None else ""
        return f"{error.get('code', 'ERROR')}{where}：{error.get('message', '')}"
    return str(error)


def _logs_text(payload: Dict[str, Any]) -> str:
    logs = payload.get("logs") or {}
    parts = [f"=== {name} ===\n{text}".rstrip() for name, text in logs.items() if text]
    console = payload.get("console")
    if console:
        parts.append("=== console ===\n" + console.rstrip())
    return "\n\n".join(parts)
