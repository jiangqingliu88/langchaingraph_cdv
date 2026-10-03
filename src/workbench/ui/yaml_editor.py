"""YAML 编辑器 —— QPlainTextEdit + 行号栏。

用 Qt 官方 CodeEditor 示例的路子：行号栏是一个覆盖在左侧的 QWidget，
靠 `blockCountChanged` / `updateRequest` / `cursorPositionChanged` 三个信号同步。

脏标志直接用 `document().isModified()` —— Qt 的实现是可靠的（tkinter 的
`edit_modified()` 一旦复位就再也收不到事件，早先那版不得不再自己记一个标志）。

**文本是模块的唯一真相**：编辑器的 `text()` 就是当前模型，其它页面都是它的
只读视图。所以这里没有「从解析结果反向生成 YAML」的路径 —— 归一化是有损的
（注释、键顺序、`RANDOM`→`RND` 这类别名改写都会丢），反向生成等于悄悄改掉
用户写的东西。有测试固定这一点。
"""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QKeyEvent, QPainter, QTextCursor,
                           QTextFormat)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from . import theme
from .highlighter import YamlHighlighter


class LineNumberArea(QWidget):
    """行号栏本身只负责转发绘制 —— 它需要编辑器的块信息才能算行号位置。"""

    def __init__(self, editor: "YamlEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)


class YamlEditor(QPlainTextEdit):
    """带行号的 YAML 编辑器。

    信号 `contentChanged(bool)`：参数表示「是否从干净变脏」——
    模块只关心这个翻转点（用来更新标题的 ●），不必每敲一个字都去问脏不脏。

    `skeleton_keys` / `enum_values` 是给高亮用的**领域词表**，由调用方传入 ——
    通用控件不该认识任何具体模型的键名。
    """

    contentChanged = Signal(bool)

    INDENT = "  "                       # YAML 缩进敏感，Tab 插入两个空格
    TAB_WIDTH = 2

    def __init__(self, parent: Optional[QWidget] = None, *,
                 skeleton_keys: Sequence[str] = (),
                 enum_values: Sequence[str] = (),
                 placeholder: str = "在此编辑 YAML，或按 Ctrl+O 打开文件…") -> None:
        super().__init__(parent)
        self._line_area = LineNumberArea(self)
        self._last_dirty = False

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(theme.mono_font())
        self.setTabStopDistance(
            self.fontMetrics().horizontalAdvance(" ") * self.TAB_WIDTH)
        self.setPlaceholderText(placeholder)
        self.document().setModified(False)

        self.highlighter = YamlHighlighter(
            self.document(), skeleton_keys=skeleton_keys,
            enum_values=enum_values)
        self.blockCountChanged.connect(self._update_area_width)
        self.updateRequest.connect(self._update_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.document().modificationChanged.connect(self._on_modification_changed)

        self._update_area_width()
        self._highlight_current_line()

    # ════════════════════════════════════════════════════════
    # 内容接口
    # ════════════════════════════════════════════════════════

    def text(self) -> str:
        """当前文本 —— **不加尾换行**。

        QPlainTextEdit 不会凭空多一个换行，所以可以直接返回 toPlainText()。
        有测试固定「载入→直接保存」逐字节相同，包括结尾换行数。
        """
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        """载入一份文本并标记为「与磁盘一致」。

        `setPlainText` 会清撤销栈 —— 换了文件之后不该还能撤销回上一个文件的内容。
        屏蔽信号是为了不让这次替换被当成「用户编辑」而标脏。
        """
        previous = self.blockSignals(True)
        try:
            self.setPlainText(text)
        finally:
            self.blockSignals(previous)
        self.document().setModified(False)
        self._last_dirty = False
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self._highlight_current_line()

    @property
    def dirty(self) -> bool:
        """有没有未保存的改动。只读 Qt 的文档标志 —— 它够可靠。"""
        return self.document().isModified()

    def mark_clean(self) -> None:
        """记为「与磁盘一致」—— 打开完成、保存成功后调用。"""
        self.document().setModified(False)

    def cursor_position(self) -> tuple:
        """(行, 列)，都从 1 开始 —— 与大多数编辑器的习惯一致。"""
        cursor = self.textCursor()
        return cursor.blockNumber() + 1, cursor.positionInBlock() + 1

    def rehighlight(self) -> None:
        """换主题后重跑高亮 —— 规则里的颜色是按主题建出来的。"""
        self.highlighter.rebuild()
        self.highlighter.rehighlight()

    def find_line(self, needle: str) -> Optional[int]:
        """按子串找行号（从 1 开始）—— 诊断跳转用。

        **优先返回非注释行**：诊断指向的是定义，而名字往往在注释里也被提过一次
        （模型的注释本来就在解释这些名字）。先命中注释会让人以为跳错了。

        逐行扫而不是用 QTextDocument.find：需要看全部匹配才能挑出非注释的那个。
        几百行的模型文件，代价可以忽略。
        """
        if not needle:
            return None
        lowered = needle.lower()
        comment_hit: Optional[int] = None
        block = self.document().begin()
        while block.isValid():
            text = block.text()
            if lowered in text.lower():
                if text.lstrip().startswith("#"):
                    comment_hit = comment_hit or block.blockNumber() + 1
                else:
                    return block.blockNumber() + 1
            block = block.next()
        return comment_hit

    def goto_line(self, line: int) -> None:
        """跳到某一行并把光标居中 —— 供「点诊断跳到出错行」用。"""
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        self.centerCursor()

    # ════════════════════════════════════════════════════════
    # 行号栏
    # ════════════════════════════════════════════════════════

    def line_number_area_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_area_width(self, _count: int = 0) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(),
                                   rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_area_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(QRect(cr.left(), cr.top(),
                                          self.line_number_area_width(),
                                          cr.height()))

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), theme.GUTTER)
        painter.setFont(self.font())
        current_line = self.cursor_position()[0]

        block = self.firstVisibleBlock()
        number = block.blockNumber() + 1
        top = round(self.blockBoundingGeometry(block)
                    .translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(theme.ACCENT if number == current_line else theme.MUTED)
                painter.drawText(0, top, self._line_area.width() - 8,
                                 self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, str(number))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    # ════════════════════════════════════════════════════════
    # 编辑行为
    # ════════════════════════════════════════════════════════

    def _highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(theme.current().current_line))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])
        self._line_area.update()

    def _on_modification_changed(self, modified: bool) -> None:
        first = modified and not self._last_dirty
        self._last_dirty = modified
        self.contentChanged.emit(first)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Tab and not event.modifiers():
            self.insertPlainText(self.INDENT)       # 别让 Tab 跳出焦点
            return
        super().keyPressEvent(event)
