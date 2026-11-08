"""维度交叉矩阵视图 —— QPainter 自绘，支持缩放与拖拽。

> 工作台第二轮上提为通用件。
> 它只按鸭子类型取 `matrix.dimensions[i].label` / `matrix.cells` /
> `matrix.mark_grid()`，不认识 case 模型的任何类型。

为什么自绘而不是用 QTableWidget：矩阵的语义是「格子 = 一对维度的交叉级别」，
不是「表格里填字」。自绘可以直接把 ★/✓/✗ 画成色块、鼠标悬停标出对应行列、
滚轮缩放、拖拽平移，也不必为每个格子建一个 item。

视口用「缩放 + 平移」两个量表达（不是改数据）：格子坐标 = 原点 + 行列 × 格宽。
所以缩放只是重算格宽，平移只是挪原点，数据和绘制逻辑都不用变。
"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..theme import palette as theme

HEADER_W = 128          # 左侧维度名列宽
HEADER_H = 34           # 顶部维度名行高（横向排，竖排中文很难读）
MIN_ZOOM, MAX_ZOOM = 0.4, 3.0
BASE_CELL = 46          # 缩放 1.0 时的格子边长
MAX_CELL = 104          # 宽度上限 —— 要放得下「5.反压持续时间」这种带序号的表头


def _elide(text: str, metrics: QFontMetrics, width: int) -> str:
    return metrics.elidedText(text or "", Qt.TextElideMode.ElideRight, width)


def draw_mark(painter: QPainter, level: str, rect: QRect, color: QColor) -> None:
    """把交叉级别画成形状，**不用字形**。

    为什么不用 ★/✓/✗ 字符：它们不是每个字体都有 —— 在只装了少量字体的环境里
    ✓ 与 ✗ 会渲染成「豆腐块」，而矩阵的核心信息就在这两个符号上。
    画形状则任何环境都一致，也不受字号/DPI 影响。

        ★ 必需 —— 实心五角星
        ○ 可选 —— 空心圆
        ✗ 禁止 —— 交叉线
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy = rect.center().x() + 1, rect.center().y() + 1
    r = max(4, min(rect.width(), rect.height()) // 2 - 7)
    pen = QPen(color, 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    if level == "required":
        import math
        points = []
        for k in range(10):
            angle = -math.pi / 2 + k * math.pi / 5
            radius = r if k % 2 == 0 else r * 0.44
            points.append(QPointF(cx + radius * math.cos(angle),
                                  cy + radius * math.sin(angle)))
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(points)
    elif level == "optional":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r * 0.72, r * 0.72)
    elif level == "forbidden":
        d = r * 0.62
        painter.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        painter.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))
    elif level == "none":
        painter.setPen(QPen(color, 1.0, Qt.PenStyle.DotLine))
        d = r * 0.5
        painter.drawLine(QPointF(cx - d, cy), QPointF(cx + d, cy))
    painter.restore()


class MatrixView(QWidget):
    """画维度交叉矩阵。

    交互（对标 Verdi 的波形区习惯）：
      · 滚轮 / Ctrl+滚轮 —— 缩放（以光标位置为锚，不会「跑掉」）
      · 中键或左键拖拽 —— 平移
      · 双击 —— 复位到自适应
      · 点格子 —— 发 `cellPicked(a, b, cell)`
    """

    cellPicked = Signal(str, str, object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._matrix = None
        self._cell = BASE_CELL
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._hover: Optional[Tuple[int, int]] = None
        self._dragging = False
        self._drag_from = QPoint(0, 0)
        self._drag_origin = QPoint(0, 0)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(240)

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def set_matrix(self, matrix) -> None:
        self._matrix = matrix
        self.reset_view()

    @property
    def matrix(self):
        return self._matrix

    def reset_view(self) -> None:
        """缩放回 1.0、平移归零 —— 换模型或双击时调。"""
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._recompute_cell()
        self.updateGeometry()
        self.update()

    @property
    def zoom(self) -> float:
        return self._zoom

    # ════════════════════════════════════════════════════════
    # 几何：格宽由「可用空间」与「缩放」共同决定
    # ════════════════════════════════════════════════════════

    def _dims(self):
        return list(self._matrix.dimensions) if self._matrix else []

    def _fit_cell(self) -> int:
        """自适应格宽 —— 让整张矩阵铺满视口（上限 BASE_CELL）。"""
        n = len(self._dims())
        if n <= 0:
            return BASE_CELL
        avail_w = max(self.width(), 480) - HEADER_W - 16
        avail_h = max(self.height(), 240) - HEADER_H - 16
        return max(18, min(MAX_CELL, min(avail_w // n, avail_h // n)))

    def _recompute_cell(self) -> None:
        self._cell = max(8, int(round(self._fit_cell() * self._zoom)))

    def _origin(self) -> QPoint:
        return QPoint(HEADER_W + self._pan.x(), HEADER_H + self._pan.y())

    def _cell_rect(self, row: int, col: int) -> QRect:
        o = self._origin()
        return QRect(o.x() + col * self._cell, o.y() + row * self._cell,
                     self._cell, self._cell)

    def sizeHint(self) -> QSize:
        n = len(self._dims())
        side = self._cell if n else BASE_CELL
        return QSize(HEADER_W + n * side + 16, HEADER_H + n * side + 16)

    # ════════════════════════════════════════════════════════
    # 绘制
    # ════════════════════════════════════════════════════════

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), theme.PANEL)

        matrix = self._matrix
        if matrix is None or not matrix.dimensions:
            painter.setPen(theme.MUTED)
            painter.drawText(16, 28, "没有可展示的维度")
            return

        dims = matrix.dimensions
        n = len(dims)
        self._recompute_cell()
        grid = matrix.mark_grid()
        origin = self._origin()
        metrics = QFontMetrics(theme.ui_font(theme.UI_SIZE))

        # 格子（先画底，再画标记）
        for i in range(n):
            for j in range(n):
                rect = self._cell_rect(i, j)
                if not rect.intersects(self.rect()):
                    continue                       # 视口外的格子不画
                if i == j:
                    fill = QColor(theme.current().panel_alt)
                else:
                    cell = matrix.cells.get((min(i, j), max(i, j)))
                    fill = theme.CROSS_LEVEL.get(cell.level if cell else "none",
                                                 theme.PANEL)
                painter.fillRect(rect, fill)
                painter.setPen(QPen(theme.GRID, 1))
                painter.drawRect(rect)
                if i == j:
                    painter.setPen(theme.MUTED)
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "—")
                else:
                    cell = matrix.cells.get((min(i, j), max(i, j)))
                    level = cell.level if cell else "none"
                    draw_mark(painter, level, rect,
                              theme.MARK.get(level, theme.TEXT))

        # 行列头：随视口平移，但裁在头部区域里，不盖住格子
        painter.save()
        painter.setClipRect(QRect(0, 0, self.width(), HEADER_H))
        for j, dim in enumerate(dims):
            x = origin.x() + j * self._cell
            if x + self._cell < HEADER_W or x > self.width():
                continue
            painter.setPen(theme.ACCENT if j == self._hover_col() else theme.TEXT)
            painter.drawText(QRect(x, 2, self._cell, HEADER_H - 4),
                             Qt.AlignmentFlag.AlignCenter,
                             _elide(f"{j + 1}.{dim.label}", metrics, self._cell - 4))
        painter.restore()

        painter.save()
        painter.setClipRect(QRect(0, HEADER_H, HEADER_W, self.height()))
        for i, dim in enumerate(dims):
            y = origin.y() + i * self._cell
            if y + self._cell < HEADER_H or y > self.height():
                continue
            painter.setPen(theme.ACCENT if i == self._hover_row() else theme.TEXT)
            painter.drawText(QRect(4, y, HEADER_W - 12, self._cell),
                             int(Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter),
                             _elide(f"{i + 1}.{dim.label}", metrics, HEADER_W - 18))
        painter.restore()

        # 左上角补一块，免得行列头在交叉处露出格子
        painter.fillRect(QRect(0, 0, HEADER_W, HEADER_H), theme.PANEL)

        self._draw_footer(painter)

    def _draw_footer(self, painter: QPainter) -> None:
        """图例 —— 用与格子相同的形状，不用字符（字符会变豆腐块）。"""
        y = self.height() - 6
        x = 8
        box = 14
        for level, name in (("required", "必需"), ("optional", "可选"),
                            ("forbidden", "禁止"), ("none", "未声明")):
            draw_mark(painter, level, QRect(x, y - 13, box, box),
                      theme.MARK.get(level, theme.MUTED))
            painter.setPen(theme.MUTED)
            width = painter.fontMetrics().horizontalAdvance(name)
            painter.drawText(x + box + 2, y - 2, name)
            x += box + 6 + width + 12
        painter.setPen(theme.MUTED)
        painter.drawText(x + 6, y - 2,
                         f"|  缩放 {self._zoom:.2f}×　滚轮缩放 · 拖拽平移 · 双击复位")

    # ════════════════════════════════════════════════════════
    # 交互
    # ════════════════════════════════════════════════════════

    def _hover_row(self) -> int:
        return self._hover[0] if self._hover else -1

    def _hover_col(self) -> int:
        return self._hover[1] if self._hover else -1

    def _hit(self, pos: QPoint) -> Optional[Tuple[int, int]]:
        n = len(self._dims())
        if not n or self._cell <= 0:
            return None
        o = self._origin()
        col = (pos.x() - o.x()) // self._cell
        row = (pos.y() - o.y()) // self._cell
        if 0 <= row < n and 0 <= col < n:
            return int(row), int(col)
        return None

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            delta = event.position().toPoint() - self._drag_from
            self._pan = self._drag_origin + delta
            self._clamp_pan()
            self.update()
            return

        hit = self._hit(event.position().toPoint())
        if hit != self._hover:
            self._hover = hit
            self.update()
        if hit is None or self._matrix is None:
            return
        row, col = hit
        dims = self._dims()
        if row == col:
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{dims[row].label}（自身）", self)
            return
        cell = self._matrix.cells.get((min(row, col), max(row, col)))
        if cell is None:
            return
        reason = f"\n理由：{cell.reason}" if cell.reason else ""
        QToolTip.showText(
            event.globalPosition().toPoint(),
            f"{dims[row].label} × {dims[col].label}\n"
            f"级别：{cell.mark} {cell.level_name}\n"
            f"来源：{cell.source}{reason}\n"
            f"（拖拽平移 / 滚轮缩放）", self)

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.MiddleButton or \
                (event.button() == Qt.MouseButton.LeftButton and self._zoom > 1.01):
            # 放大了才让左键拖拽 —— 未放大时左键留给「点格子看详情」
            self._dragging = True
            self._drag_from = pos
            self._drag_origin = QPoint(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton or self._matrix is None:
            return
        hit = self._hit(pos)
        if hit is None:
            return
        row, col = hit
        if row == col:
            return
        cell = self._matrix.cells.get((min(row, col), max(row, col)))
        if cell is not None:
            dims = self._dims()
            self.cellPicked.emit(dims[row].label, dims[col].label, cell)

    def mouseReleaseEvent(self, _event) -> None:
        if self._dragging:
            self._dragging = False
            self.unsetCursor()

    def mouseDoubleClickEvent(self, _event) -> None:
        self.reset_view()

    def wheelEvent(self, event) -> None:
        """以光标为锚缩放 —— 锚点不动，才不会「缩放时矩阵跑掉」。"""
        if self._matrix is None:
            return
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        anchor = event.position().toPoint()
        before = self._hit(anchor)

        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom * (1.15 ** steps)))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        self._zoom = new_zoom
        self._recompute_cell()

        # 让锚点下的那一格保持在原地
        if before is not None:
            row, col = before
            o = self._origin()
            want = QPoint(
                anchor.x() - (col + 0.5) * self._cell,
                anchor.y() - (row + 0.5) * self._cell)
            self._pan = QPoint(want.x() - HEADER_W, want.y() - HEADER_H)
            self._clamp_pan()
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._clamp_pan()

    def _clamp_pan(self) -> None:
        """别让矩阵被拖出视口 —— 至少留一格可见。"""
        n = len(self._dims())
        if not n:
            self._pan = QPoint(0, 0)
            return
        side = n * self._cell
        max_x = max(0, side - max(0, self.width() - HEADER_W) + 24)
        max_y = max(0, side - max(0, self.height() - HEADER_H) + 24)
        self._pan = QPoint(min(max(self._pan.x(), -max_x), 24),
                           min(max(self._pan.y(), -max_y), 24))
