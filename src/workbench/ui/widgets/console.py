"""控制台 —— 全平台唯一的「发生了什么」出口。

为什么必须有：工作台上的动作大多是**跑一个外部工具**，成功时安静、失败时
只有一句 traceback。把结果只塞进模块自己的表格里，用户切走标签页就再也
找不回来了。控制台是那条不会被切走的时间线。

按级别着色而不是加时间戳前缀：时间戳在「刚点完按钮」的场景没有信息量，
颜色能让人一眼扫出红色的那几行。真要时间戳，`QPlainTextEdit` 的块里存了
级别，将来加导出很容易。
"""
from __future__ import annotations

from html import escape
from typing import Optional

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..theme import palette as theme

#: 级别由低到高。过滤框按「至少这个级别」筛。
LEVELS = ("debug", "info", "warning", "error")
LEVEL_ORDER = {name: i for i, name in enumerate(LEVELS)}

#: 级别 → `theme.current()` 上的颜色字段名
_LEVEL_FIELD = {"debug": "muted", "info": "text",
                "warning": "warning", "error": "error"}

#: 日志最多留多少行 —— 仿真日志动辄几十万行，不设上限会把内存吃完
MAX_BLOCKS = 5000


class ConsolePanel(QWidget):
    """分级日志 + 任务进度行。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._min_level = "debug"
        self._lines: list = []          # [(level, text)]，用于按级别重放

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(3)
        layout.addLayout(self._build_bar())

        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_BLOCKS)
        self.view.setFont(theme.mono_font())
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.view, 1)

        self.task_label = QLabel("", self)
        self.task_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.task_label)

    def _build_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(4)
        bar.addWidget(QLabel("级别", self))
        self.level_box = QComboBox(self)
        self.level_box.addItems(LEVELS)
        self.level_box.setCurrentText("info")
        self.level_box.currentTextChanged.connect(self.set_min_level)
        bar.addWidget(self.level_box)
        bar.addStretch(1)

        self.btn_copy = QPushButton("复制", self)
        self.btn_copy.clicked.connect(self.copy_all)
        bar.addWidget(self.btn_copy)

        self.btn_clear = QPushButton("清空", self)
        self.btn_clear.clicked.connect(self.clear_log)
        bar.addWidget(self.btn_clear)
        return bar

    # ── 写 ──

    def append(self, text: str, level: str = "info") -> None:
        """记一行。`text` 可以是多行 —— 仿真日志的报错块天然是多行的。"""
        level = level if level in LEVEL_ORDER else "info"
        for line in str(text).splitlines() or [""]:
            self._lines.append((level, line))
        self._append_visible(level, text)

    def _append_visible(self, level: str, text: str) -> None:
        if LEVEL_ORDER[level] < LEVEL_ORDER[self._min_level]:
            return
        color = getattr(theme.current(), _LEVEL_FIELD[level])
        body = escape(str(text)).replace("\n", "<br>")
        self.view.appendHtml(f"<span style='color:{color}'>{body}</span>")
        self.view.verticalScrollBar().setValue(
            self.view.verticalScrollBar().maximum())

    # ── 过滤 / 清空 / 复制 ──

    def set_min_level(self, level: str) -> None:
        """改过滤级别 —— 按已有的行**重放**一遍，而不是从此刻起才生效。

        重放而不是「以后才生效」：用户切到「只看 error」的动机通常正是想
        回看刚才那一屏里的红色行，只对未来的行生效等于什么都没做。
        """
        self._min_level = level if level in LEVEL_ORDER else "debug"
        self.view.clear()
        for lvl, text in self._lines:
            self._append_visible(lvl, text)

    def clear_log(self) -> None:
        self._lines.clear()
        self.view.clear()

    def copy_all(self) -> None:
        QGuiApplication.clipboard().setText(self.view.toPlainText())

    def lines(self) -> list:
        """`[(level, text)]` —— 测试与将来的导出用。"""
        return list(self._lines)

    # ── 任务进度行 ──

    def begin_task(self, label: str) -> None:
        self.task_label.setText(f"● {label} …")
        self.task_label.setStyleSheet(f"color: {theme.current().accent};")

    def end_task(self, label: str = "", ok: bool = True) -> None:
        if not label:
            self.task_label.setText("")
            return
        mark, color = ("✓", theme.current().ok) if ok else ("✗", theme.current().error)
        self.task_label.setText(f"{mark} {label}")
        self.task_label.setStyleSheet(f"color: {color};")
