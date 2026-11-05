"""占位视图 —— 界面上有位置、但没有真实数据源的那些页面。

存在的理由：原理图与状态机的交互位置是确定要的（它们在 Verdi 的工作流里
不可替代），但本仓库**没有**网表/原理图读取器，也没有状态机提取器。与其
把它们从界面上删掉、等将来重做一遍信息架构，不如先把位置占住。

**唯一的硬规则：不许让人误以为能用。** 所以这类页面顶部常驻一条琥珀色
横幅（`banner.PermanentNote`，关不掉），画布上再写一遍「演示数据」。
一条能被习惯性无视的提示等于没有提示 —— 这里宁可显得啰嗦。

将来接上真实数据源时，把本类换掉即可，`placeholder: true` 标记一并去掉。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QLabel, QSizePolicy, QVBoxLayout, QWidget)

from ..theme import palette as theme
from .banner import PermanentNote

DEFAULT_NOTE = ("演示数据 —— 本视图没有接真实数据源，画面上的一切都是示意，"
                "不代表任何实际设计。")

#: 画布上示意格网的间距（像素）
GRID_STEP = 28


class DemoCanvas(QWidget):
    """一块自绘的示意画布 —— 格网 + 居中说明文字。

    不做「假装很多数据的动效」：占位就该看起来像占位。
    """

    def __init__(self, note: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.note = note or DEFAULT_NOTE
        self.setMinimumSize(280, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    def paintEvent(self, event) -> None:             # noqa: N802  Qt 接口
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.current().q("panel"))
        self._paint_grid(painter)
        self._paint_note(painter)
        painter.end()

    def _paint_grid(self, painter: QPainter) -> None:
        pen = QPen(theme.GRID)
        pen.setWidth(1)
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        for x in range(0, self.width(), GRID_STEP):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), GRID_STEP):
            painter.drawLine(0, y, self.width(), y)

    def _paint_note(self, painter: QPainter) -> None:
        painter.setPen(QPen(theme.MUTED))
        painter.setFont(theme.ui_font())
        rect = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter) |
                         int(Qt.TextFlag.TextWordWrap), self.note)


class PaintedPlaceholder(QWidget):
    """占位页面的标准形态：常驻琥珀横幅 + 示意画布（+ 可选的一行提示）。"""

    def __init__(self, title: str = "", note: str = "", hint: str = "",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        headline = f"{title}：{DEFAULT_NOTE}" if title else DEFAULT_NOTE
        self.note_banner = PermanentNote(headline, "warning", self)
        layout.addWidget(self.note_banner)

        if hint:
            hint_label = QLabel(hint, self)
            hint_label.setWordWrap(True)
            hint_label.setStyleSheet(f"color: {theme.current().muted};")
            layout.addWidget(hint_label)

        self.canvas = DemoCanvas(note or headline, self)
        layout.addWidget(self.canvas, 1)
