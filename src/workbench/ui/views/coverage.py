"""取值覆盖视图 —— QPainter 自绘的横向条。

每行一个维度：左边维度名，中间覆盖条，右边命中/总数。联动派生字段的维度标灰 ——
它的取值跟随被联动字段，不是独立的缺口，视觉上不该和真缺口一样红。

> 工作台第二轮上提为通用件。按鸭子
> 类型取 `row.name / ratio / hit_count / total / key / derived_only`。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import palette as theme

ROW_H = 26
LABEL_W = 150
COUNT_W = 90


class CoverageView(QWidget):
    """每行一个维度。点某行发 `rowPicked(dimension_key)`。"""

    rowPicked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_coverage(self, dimension_coverage: List) -> None:
        self._rows = list(dimension_coverage)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(560, max(80, len(self._rows) * ROW_H + 20))

    def minimumSizeHint(self) -> QSize:
        return QSize(280, max(80, len(self._rows) * ROW_H + 20))

    def _bar_color(self, row) -> QColor:
        if getattr(row, "derived_only", False):
            return theme.COVERAGE["derived"]
        if row.ratio >= 0.999:
            return theme.COVERAGE["full"]
        return theme.COVERAGE["part"] if row.ratio > 0 else theme.COVERAGE["none"]

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 底色与槽色都跟主题走。原先写死 white / #eceff1 —— 那是照浅色背景调的，
        # 放到深色主题上会撕出一大块白，而这正是「上提为平台通用件」要修掉的东西。
        palette = theme.current()
        painter.fillRect(self.rect(), QColor(palette.panel))
        metrics = QFontMetrics(theme.ui_font(9))

        if not self._rows:
            painter.setPen(theme.MUTED)
            painter.drawText(16, 28, "没有维度")
            return

        bar_x = LABEL_W
        bar_w = max(60, self.width() - LABEL_W - COUNT_W - 16)

        for i, row in enumerate(self._rows):
            y = 10 + i * ROW_H
            hovered = i == self._hover
            painter.setPen(theme.SEVERITY["info"] if hovered else theme.TEXT)
            painter.drawText(QRect(4, y, LABEL_W - 12, ROW_H - 8),
                             int(Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter),
                             metrics.elidedText(row.name, Qt.TextElideMode.ElideRight,
                                                LABEL_W - 16))
            track = QRect(bar_x, y + 4, bar_w, ROW_H - 16)
            painter.fillRect(track, QColor(palette.panel_alt))
            fill = QRect(track.left(), track.top(),
                         max(1, int(bar_w * row.ratio)), track.height())
            painter.fillRect(fill, self._bar_color(row))
            painter.setPen(QPen(theme.GRID, 1))
            painter.drawRect(track)
            painter.setPen(theme.MUTED)
            painter.drawText(QRect(bar_x + bar_w + 8, y, COUNT_W - 8, ROW_H - 8),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"{row.hit_count}/{row.total}  {row.ratio:.0%}")

    def _hit(self, y: int) -> int:
        idx = (y - 10) // ROW_H
        return int(idx) if 0 <= idx < len(self._rows) else -1

    def mouseMoveEvent(self, event) -> None:
        idx = self._hit(int(event.position().y()))
        if idx != self._hover:
            self._hover = idx
            self.update()

    def mousePressEvent(self, event) -> None:
        idx = self._hit(int(event.position().y()))
        if idx >= 0:
            self.rowPicked.emit(self._rows[idx].key)
