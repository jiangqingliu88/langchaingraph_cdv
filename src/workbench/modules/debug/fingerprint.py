"""错误指纹 —— 把一段报错压成一个可比较的指纹。

用途很具体：同一类错误在回归里会出现几十次，报错文本里的行号、地址、时间
各不相同。指纹去掉了这些会变的部分，于是「这是同一个 bug」变成一个可以
`==` 的判断。指纹本身由 `debug_tools.fingerprint_error` 算，这里不重复实现。

为什么做成底部 Dock 而不是中央标签页：它的用法是**贴一段、看一眼、切走**。
占中央位置会挤掉真正要长时间盯着的东西（日志、波形）。
"""
from __future__ import annotations

import json
from typing import Any, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QSplitter, QVBoxLayout, QWidget)

from ...ui import theme
from ...ui.helpers import tables as table_helpers
from ...ui.models import LEFT, RowsModel
from ..base import ModuleBase

#: 键 / 值 两列 —— 工具返回的扁平 dict 直接铺开
COLUMNS = (("键", "键", 150, LEFT), ("值", "值", 420, LEFT))

SAMPLE = ("ERROR: tb_fifo.sv(128): Undefined variable 'rd_ptr'\n"
          "  near \"rd_ptr <= 0\"\n")


class FingerprintModule(ModuleBase):
    """贴错误文本 → 取指纹 + 归类。"""

    HINT = "贴一段报错文本，取它的指纹（去掉行号/地址后可比对）。"

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Vertical, root)

        # ── 输入 ──
        top = QWidget(splitter)
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(3)

        bar = QHBoxLayout()
        hint = QLabel(self.HINT, top)
        hint.setStyleSheet(f"color: {theme.current().muted};")
        bar.addWidget(hint)
        bar.addStretch(1)
        self.btn_sample = QPushButton("填入示例", top)
        self.btn_sample.clicked.connect(lambda: self.editor.setPlainText(SAMPLE))
        bar.addWidget(self.btn_sample)
        self.btn_run = QPushButton("取指纹", top)
        self.btn_run.setDefault(True)
        self.btn_run.clicked.connect(self.take_fingerprint)
        bar.addWidget(self.btn_run)
        top_layout.addLayout(bar)

        self.editor = QPlainTextEdit(top)
        self.editor.setPlaceholderText("把编译/仿真报错整段贴进来，多行也行")
        self.editor.setFont(theme.mono_font())
        self.editor.setPlainText(SAMPLE)
        top_layout.addWidget(self.editor, 1)
        splitter.addWidget(top)

        # ── 结果 ──
        bottom = QWidget(splitter)
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(3)
        self.summary = QLabel("还没有取过指纹。", bottom)
        self.summary.setStyleSheet(f"color: {theme.current().muted};")
        bottom_layout.addWidget(self.summary)

        self.model = RowsModel(COLUMNS, bottom)
        self.table = table_helpers.configure_table(bottom, self.model)
        bottom_layout.addWidget(self.table, 1)
        splitter.addWidget(bottom)

        splitter.setSizes([200, 260])
        layout.addWidget(splitter, 1)
        return root

    # ── 动作 ──

    def create_actions(self) -> List[QAction]:
        """菜单与工具栏里的动作 —— 让「错误指纹」出现在**调试菜单**下。

        没有这个方法时，本模块只在「窗口」菜单里有一个显隐开关，
        调试菜单里什么都没有（`registry.py` 只把模块 `create_actions()`
        的结果挂到业务线菜单）。

        文案不写"取指纹"而写"错误指纹"：菜单里这一条是**这个模块的入口**
        （上面已经有模块标题作分隔行），叫"取指纹"会和旁边那些动词混在一起
        看不出是谁的。hint 里再补一句它到底做什么。
        """
        take = QAction("错误指纹", self.content)
        take.setStatusTip("把当前输入框里的报错文本压成指纹（去掉行号/地址后可比对）")
        take.triggered.connect(self.take_fingerprint)

        sample = QAction("填入示例", self.content)
        sample.setStatusTip("把输入框换成本模块自带的示例报错")
        sample.triggered.connect(lambda: self.editor.setPlainText(SAMPLE))
        return [take, sample]

    def take_fingerprint(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            self.show_warning("还没有输入报错文本。")
            return
        payload = self.run_tool(error_text=text)
        self._render(payload)

    # ── 渲染 ──

    def _render(self, payload: Any) -> None:
        if payload is None:                     # run_tool 已经报过错了
            return
        if self.report_payload_error(payload):
            self.model.set_rows([])
            self.summary.setText("工具返回的是一条错误 —— 见上方横幅。")
            return

        rows = _flat_rows(payload)
        self.model.set_rows(rows)
        fingerprint = payload.get("fingerprint") if isinstance(payload, dict) else None
        self.summary.setText(
            f"指纹 {fingerprint}　（{len(rows)} 项）"
            if fingerprint else f"取到 {len(rows)} 项")
        self.set_status(f"错误指纹：{fingerprint or '（无）'}")


def _flat_rows(payload: Any) -> List[dict]:
    """把工具结果铺成「键 / 值」两列。

    只展开**一层**嵌套：再深就该去看原始 JSON 了，硬铺进表格反而看不清
    结构。指纹工具的结果只有 `classification` 一个嵌套 dict，展开一层刚好。
    """
    if isinstance(payload, dict):
        rows: List[dict] = []
        for key, value in payload.items():
            if isinstance(value, dict):
                rows.append({"键": str(key), "值": f"（{len(value)} 项）"})
                rows.extend({"键": f"　{k}", "值": _text(v)}
                            for k, v in value.items())
            else:
                rows.append({"键": str(key), "值": _text(value)})
        return rows
    if isinstance(payload, list):
        return [{"键": f"[{i}]", "值": _text(item)}
                for i, item in enumerate(payload)]
    return [{"键": "值", "值": _text(payload)}]


def _text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)
