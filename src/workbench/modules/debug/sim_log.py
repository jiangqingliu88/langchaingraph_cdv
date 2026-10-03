"""仿真日志 —— 两条路：手上有文本就贴，有 output 目录就去扫。

做成**两条路**而不是一条，是因为调试的时候手上有什么是不确定的：

  · 「粘贴日志」走 `lib.sim_log` 的三个纯函数（正则解析，不依赖任何 EDA
    工具，也不依赖目录结构）。远程机器上把日志贴过来就能看，这在排查
    别人机器上的失败时是常态。
  · 「扫描输出目录」走 `debug_tools.collect_sim_log`，它按 `output/<regress>/
    sim/**/sim_*.log` 的约定去翻，能一次汇总几百个 case 的错误并归类。

结果区分两页：「结果摘要」是铺平的一层表格，「原始结果」是工具的完整 JSON。
摘要让人一眼看完，JSON 保证**没有任何信息被界面藏起来** —— 只有摘要的话，
工具多返回一个字段界面就丢了，那种丢失很难被发现。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from ...ui import table_helpers, theme
from ...ui.models import LEFT, RowsModel
from ..base import ModuleBase

#: 键 / 值 两列
COLUMNS = (("键", "键", 220, LEFT), ("值", "值", 420, LEFT))

SAMPLE = (
    "# UVM_INFO: running tc_fifo_basic\n"
    "UVM_ERROR @ 1250ns: tb_fifo.sv(128) | mismatched: 3\n"
    "UVM_WARNING @ 1260ns: scoreboard timeout approaching\n"
    "[SCB_LOOP] checked=40 matched=37 mismatched=3\n"
    "driven: 40\n"
)


class SimLogModule(ModuleBase):
    """仿真/编译日志的解析与汇总。"""

    HINT = "贴一段日志直接解析，或指定一个 output 目录批量扫描。"

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel(self.HINT, root)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Vertical, root)

        self.source_tabs = QTabWidget(splitter)
        self.source_tabs.addTab(self._build_paste_page(), "粘贴日志")
        self.source_tabs.addTab(self._build_dir_page(), "扫描输出目录")
        splitter.addWidget(self.source_tabs)

        self.result_tabs = QTabWidget(splitter)
        self.result_tabs.addTab(self._build_summary_page(), "结果摘要")
        self.result_tabs.addTab(self._build_raw_page(), "原始结果")
        splitter.addWidget(self.result_tabs)

        splitter.setSizes([280, 340])
        layout.addWidget(splitter, 1)
        return root

    # ════════════════════════════════════════════════════════
    # 控件
    # ════════════════════════════════════════════════════════

    def _build_paste_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        self.btn_open_file = QPushButton("打开日志文件…", page)
        self.btn_open_file.clicked.connect(self.open_log_file)
        bar.addWidget(self.btn_open_file)

        self.btn_sample = QPushButton("填入示例", page)
        self.btn_sample.clicked.connect(lambda: self.editor.setPlainText(SAMPLE))
        bar.addWidget(self.btn_sample)
        bar.addStretch(1)

        self.btn_parse = QPushButton("解析仿真日志", page)
        self.btn_parse.clicked.connect(self.parse_pasted)
        bar.addWidget(self.btn_parse)

        self.btn_compile = QPushButton("分析编译日志", page)
        self.btn_compile.clicked.connect(self.analyze_compile)
        bar.addWidget(self.btn_compile)
        layout.addLayout(bar)

        self.editor = QPlainTextEdit(page)
        self.editor.setPlaceholderText("把 vsim / 编译输出整段贴进来")
        self.editor.setFont(theme.mono_font())
        layout.addWidget(self.editor, 1)
        return page

    def _build_dir_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        note = QLabel(
            "按 output/<回归目录>/sim/**/sim_*.log 的约定去扫，汇总所有 case 的\n"
            "错误并按指纹归类。目录不存在时工具会直说，不会假装扫过了。",
            page)
        note.setStyleSheet(f"color: {theme.current().muted};")
        note.setWordWrap(True)
        layout.addWidget(note)

        bar = QHBoxLayout()
        self.dir_edit = QLineEdit(page)
        self.dir_edit.setPlaceholderText("output 目录（留空 = ./output）")
        bar.addWidget(self.dir_edit, 1)

        self.btn_browse = QPushButton("浏览…", page)
        self.btn_browse.clicked.connect(self.browse_output_dir)
        bar.addWidget(self.btn_browse)

        self.btn_scan = QPushButton("扫描", page)
        self.btn_scan.clicked.connect(self.scan_output_dir)
        bar.addWidget(self.btn_scan)
        layout.addLayout(bar)
        layout.addStretch(1)
        return page

    def _build_summary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.summary = QLabel("还没有解析过。", page)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.model = RowsModel(COLUMNS, page)
        self.table = table_helpers.configure_table(page, self.model)
        layout.addWidget(self.table, 1)
        return page

    def _build_raw_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        self.raw = QPlainTextEdit(page)
        self.raw.setReadOnly(True)
        self.raw.setFont(theme.mono_font())
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.raw.setPlaceholderText("工具的完整返回值会出现在这里")
        layout.addWidget(self.raw, 1)
        return page

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def on_input_changed(self, path) -> None:
        """清单的 `input` 或 `--input` 指过来时：是目录就当扫描目标填进去。"""
        target = Path(path)
        if target.is_dir():
            self.dir_edit.setText(str(target))
            self.source_tabs.setCurrentIndex(1)
            self.set_status(f"扫描目标：{target}")
        elif target.is_file():
            try:
                self.editor.setPlainText(_read_text(str(target)))
            except OSError as exc:
                self.show_error(f"读不了这个文件：{exc}")
                return
            self.source_tabs.setCurrentIndex(0)
            self.set_status(f"已载入 {target}")

    # ════════════════════════════════════════════════════════
    # 动作
    # ════════════════════════════════════════════════════════

    def open_log_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self.content, "选择日志文件", "",
            "日志 (*.log *.txt);;所有文件 (*)")
        if not path:
            return
        try:
            text = _read_text(path)
        except OSError as exc:
            self.show_error(f"读不了这个文件：{exc}")
            return
        self.editor.setPlainText(text)
        self.source_tabs.setCurrentIndex(0)
        self.set_status(f"已载入 {path}（{len(text.splitlines())} 行）")
        self.log(f"载入日志文件 {path}")

    def parse_pasted(self) -> None:
        text = self.editor.toPlainText()
        if not text.strip():
            self.show_warning("还没有日志文本 —— 贴一段，或载入一个日志文件。")
            return
        self._show(self.run_tool("sim.parse_log", log_text=text), "仿真日志解析")

    def analyze_compile(self) -> None:
        text = self.editor.toPlainText()
        if not text.strip():
            self.show_warning("还没有日志文本 —— 贴一段，或载入一个日志文件。")
            return
        self._show(self.run_tool("sim.analyze_compile", log_text=text), "编译日志分析")

    def browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self.content, "选择 output 目录")
        if path:
            self.dir_edit.setText(path)

    def scan_output_dir(self) -> None:
        target = self.dir_edit.text().strip() or "output"
        self.set_status(f"正在扫描 {target} …")
        self._show(self.run_tool(output_dir=target), f"扫描 {target}")

    # ════════════════════════════════════════════════════════
    # 渲染
    # ════════════════════════════════════════════════════════

    def _show(self, payload: Any, title: str) -> None:
        if payload is None:                       # run_tool 已经报过错了
            return
        self.raw.setPlainText(_pretty(payload))
        self.result_tabs.setCurrentIndex(0)

        if self.report_payload_error(payload):
            self.model.set_rows([])
            self._set_summary("工具返回的是一条错误 —— 见上方横幅。", None)
            return

        rows = _flat_rows(payload)
        self.model.set_rows(rows)
        self._set_summary(f"{title}：{len(rows)} 项", _status_of(payload))
        self.set_status(f"{title} —— {len(rows)} 项")

    def _set_summary(self, text: str, status: Optional[str]) -> None:
        """摘要行按 PASS/FAIL 着色 —— 这是看日志的人第一眼要找的东西。

        用**词**而不是图标：PASS / FAIL 是能在日志里 grep 到、也能被测试断言的
        东西，一个 ✓ 不是。颜色只是帮助扫读，不承担信息。
        """
        palette = theme.current()
        prefix, color = "", palette.muted
        if status == "PASS":
            prefix, color = "PASS　", palette.ok
        elif status == "FAIL":
            prefix, color = "FAIL　", palette.error
        self.summary.setStyleSheet(f"color: {color};")
        self.summary.setText(f"{prefix}{text}")


# ════════════════════════════════════════════════════════════
# 纯函数
# ════════════════════════════════════════════════════════════

def _read_text(path: str) -> str:
    """日志多半不是 UTF-8（工具链常写 GBK），坏字节直接替换而不是抛。"""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _pretty(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _status_of(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if isinstance(status, str) and status.upper() in ("PASS", "FAIL"):
        return status.upper()
    passed = payload.get("passed")
    if isinstance(passed, bool):
        return "PASS" if passed else "FAIL"
    return None


def _flat_rows(payload: Any) -> List[dict]:
    """铺成「键 / 值」。嵌套只展开一层，深层结构交给「原始结果」页。"""
    if not isinstance(payload, dict):
        return _rows_of_sequence(payload)

    rows: List[dict] = []
    for key, value in payload.items():
        if isinstance(value, dict):
            rows.append({"键": str(key), "值": f"（{len(value)} 项）"})
            rows.extend({"键": f"　{k}", "值": _scalar(v)} for k, v in value.items())
        elif isinstance(value, list):
            rows.append({"键": str(key), "值": f"（{len(value)} 项）"})
            for index, item in enumerate(value):
                rows.append({"键": f"　[{index}]", "值": _scalar(item)})
        else:
            rows.append({"键": str(key), "值": _scalar(value)})
    return rows


def _rows_of_sequence(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        return [{"键": f"[{i}]", "值": _scalar(item)}
                for i, item in enumerate(payload)]
    if payload is None:
        return []
    return [{"键": "值", "值": _scalar(payload)}]


def _scalar(value: Any) -> str:
    """一行里放得下的那种文本；嵌套结构压成一行 JSON 而不是消失。"""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
        return text if len(text) <= 300 else text[:297] + "…"
    if isinstance(value, bool):
        return "是" if value else "否"
    return "" if value is None else str(value)
