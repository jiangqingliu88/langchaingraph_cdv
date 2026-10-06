"""趋势折线图 —— QPainter 自绘的多序列折线。

为什么不引 QtCharts / matplotlib：本仓库的图形件一律自绘（见 `coverage_view` /
`matrix_view` 的说明）—— 自绘没有依赖，配色跟主题走，字体/DPI 也可控。折线图
要的东西（坐标映射、网格、图例）不多，不值得为它破例引一个图表库。

按**鸭子类型**吃数据：每条序列是一个 dict `{id, title, points}`，`points` 是
`[[x, y], ...]`（x 是轮次、y 是要画的量）。颜色由本组件按序列顺序分配 ——
调用方只管给数据，不操心配色，两个面板因此天然不撞色。

    chart.set_series(payload["test_series"], y_max=100, unit="%")
    chart.pointHovered.connect(lambda sid, rnd, val: ...)

鼠标悬停最近的点会发 `pointHovered(series_id, x, y)` —— 谁想显示细节谁接。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import palette as theme

#: 序列配色 —— 中饱和度，浅色/深色主题都读得清。按序列顺序循环取用。
SERIES_COLORS = ("#4a90d9", "#6cc070", "#e0a020", "#d9534f",
                 "#9b6bd6", "#3fb5b5", "#d67ab1", "#8a8f98")

PAD_LEFT = 54        # 左侧留给 y 轴刻度
PAD_RIGHT = 138      # 右侧留给图例（阶段名可能较长）
PAD_TOP = 30         # 顶部留给面板标题
PAD_BOTTOM = 34      # 底部留给 x 轴轮次标签
HIT_RADIUS = 9.0     # 悬停命中半径（像素）
Y_TICKS = 5


class TrendChart(QWidget):
    """多序列折线图。`set_series` 一次给全套数据。"""

    #: (series_id, x, y) —— 鼠标悬停到某个数据点时发。
    pointHovered = Signal(str, int, float)

    def __init__(self, parent: Optional[QWidget] = None, *, panel_title: str = "") -> None:
        super().__init__(parent)
        self._panel_title = panel_title
        self._series: List[Dict[str, Any]] = []
        self._unit = ""
        self._y_max: Optional[float] = None
        self._rounds: List[int] = []
        self._hover: Optional[tuple] = None      # (series_id, x, y)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(160)

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def set_series(self, series: Optional[List[Dict[str, Any]]], *,
                   y_max: Optional[float] = None, unit: str = "",
                   panel_title: Optional[str] = None) -> None:
        """给一整套序列。

        `y_max` 给了就固定 y 轴上限（如百分比固定 100），不给就按数据自适应。
        """
        self._series = []
        for index, raw in enumerate(series or []):
            points = [[int(p[0]), float(p[1])] for p in (raw.get("points") or [])
                      if len(p) >= 2]
            if not points:
                continue                      # 空序列不占图例、不连线
            self._series.append({
                "id": str(raw.get("id", "")),
                "title": str(raw.get("title", raw.get("id", ""))),
                "points": points,
                "color": QColor(SERIES_COLORS[index % len(SERIES_COLORS)]),
            })
        self._unit = unit
        self._y_max = y_max
        if panel_title is not None:
            self._panel_title = panel_title
        self._rounds = sorted({int(p[0]) for s in self._series for p in s["points"]})
        self._hover = None
        self.update()

    # ════════════════════════════════════════════════════════
    # 尺寸
    # ════════════════════════════════════════════════════════

    def sizeHint(self) -> QSize:
        return QSize(560, 240)

    def minimumSizeHint(self) -> QSize:
        return QSize(320, 160)

    # ════════════════════════════════════════════════════════
    # 绘制
    # ════════════════════════════════════════════════════════

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = theme.current()
        painter.fillRect(self.rect(), QColor(palette.panel))

        metrics = QFontMetrics(theme.ui_font(9))
        painter.setFont(theme.ui_font(9))

        if not self._series:
            painter.setPen(theme.MUTED)
            painter.drawText(16, 28, "（还没有数据）")
            return

        plot = QRect(PAD_LEFT, PAD_TOP, max(40, self.width() - PAD_LEFT - PAD_RIGHT),
                     max(40, self.height() - PAD_TOP - PAD_BOTTOM))
        y_max = self._y_max if self._y_max is not None else self._auto_y_max()

        self._draw_frame(painter, plot, y_max, metrics)
        self._draw_lines(painter, plot, y_max)
        self._draw_legend(painter, metrics)
        painter.setPen(theme.TEXT)
        painter.drawText(QRect(8, 6, self.width() - 16, PAD_TOP - 8),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self._panel_title)

    def _auto_y_max(self) -> float:
        top = max((p[1] for s in self._series for p in s["points"]), default=1.0)
        return top if top > 0 else 1.0

    def _x_to_px(self, x: float, plot: QRect) -> float:
        if len(self._rounds) <= 1:
            return plot.left() + plot.width() / 2
        lo, hi = self._rounds[0], self._rounds[-1]
        span = hi - lo or 1
        return plot.left() + (x - lo) / span * plot.width()

    @staticmethod
    def _y_to_px(y: float, plot: QRect, y_max: float) -> float:
        ratio = 0.0 if y_max <= 0 else max(0.0, min(1.0, y / y_max))
        return plot.bottom() - ratio * plot.height()

    def _draw_frame(self, painter: QPainter, plot: QRect, y_max: float,
                    metrics: QFontMetrics) -> None:
        """网格 + y 轴刻度 + x 轴轮次标签。"""
        for i in range(Y_TICKS + 1):
            value = y_max * i / Y_TICKS
            y = self._y_to_px(value, plot, y_max)
            painter.setPen(QPen(theme.GRID, 1, Qt.PenStyle.DotLine))
            painter.drawLine(plot.left(), int(y), plot.right(), int(y))
            painter.setPen(theme.MUTED)
            label = f"{value:.0f}{self._unit}"
            painter.drawText(QRect(4, int(y) - 9, PAD_LEFT - 10, 18),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             label)

        painter.setPen(QPen(theme.GRID, 1))
        painter.drawRect(plot)
        painter.setPen(theme.MUTED)
        for rnd in self._rounds:
            x = int(self._x_to_px(rnd, plot))
            painter.drawText(QRect(x - 20, plot.bottom() + 4, 40, 18),
                             Qt.AlignmentFlag.AlignCenter, f"R{rnd}")

    def _draw_lines(self, painter: QPainter, plot: QRect, y_max: float) -> None:
        for series in self._series:
            color = series["color"]
            pixels = [(self._x_to_px(p[0], plot), self._y_to_px(p[1], plot, y_max),
                       p[0], p[1]) for p in series["points"]]

            painter.setPen(QPen(color, 2))
            if len(pixels) > 1:
                for (x1, y1, *_),(x2, y2, *_) in zip(pixels, pixels[1:]):
                    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            for (x, y, _rnd, _val) in pixels:
                painter.setBrush(color)
                painter.setPen(QPen(color, 1))
                painter.drawEllipse(QPointF(x, y), 3.2, 3.2)

        if self._hover is not None:
            series = self._series_by_id(self._hover[0])
            if series is not None:
                x = self._x_to_px(self._hover[1], plot)
                y = self._y_to_px(self._hover[2], plot, y_max)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(theme.current().accent), 2))
                painter.drawEllipse(QPointF(x, y), HIT_RADIUS, HIT_RADIUS)

    def _draw_legend(self, painter: QPainter, metrics: QFontMetrics) -> None:
        """右侧竖排图例：色块 + 阶段名 + 末值。"""
        x = self.width() - PAD_RIGHT + 12
        y = PAD_TOP
        for series in self._series:
            color = series["color"]
            painter.setBrush(color)
            painter.setPen(QPen(color, 1))
            painter.drawRect(x, y + 3, 10, 10)
            painter.setPen(theme.TEXT)
            last = series["points"][-1][1]
            text = f"{series['title']}  {last:.0f}{self._unit}"
            painter.drawText(QRect(x + 16, y, PAD_RIGHT - 30, 16),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                                PAD_RIGHT - 30))
            y += 18

    # ════════════════════════════════════════════════════════
    # 交互
    # ════════════════════════════════════════════════════════

    def _series_by_id(self, series_id: str) -> Optional[Dict[str, Any]]:
        for series in self._series:
            if series["id"] == series_id:
                return series
        return None

    def mouseMoveEvent(self, event) -> None:
        if not self._series:
            return
        plot = QRect(PAD_LEFT, PAD_TOP, max(40, self.width() - PAD_LEFT - PAD_RIGHT),
                     max(40, self.height() - PAD_TOP - PAD_BOTTOM))
        y_max = self._y_max if self._y_max is not None else self._auto_y_max()
        px, py = event.position().x(), event.position().y()

        best = None
        best_dist = HIT_RADIUS ** 2
        for series in self._series:
            for (x_val, y_val) in series["points"]:
                sx = self._x_to_px(x_val, plot)
                sy = self._y_to_px(y_val, plot, y_max)
                dist = (sx - px) ** 2 + (sy - py) ** 2
                if dist <= best_dist:
                    best_dist = dist
                    best = (series["id"], int(x_val), float(y_val))
        if best != self._hover:
            self._hover = best
            self.update()
            if best is not None:
                self.pointHovered.emit(best[0], best[1], best[2])

    def leaveEvent(self, _event) -> None:
        if self._hover is not None:
            self._hover = None
            self.update()
