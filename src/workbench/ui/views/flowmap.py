"""闭环流程视图 —— 把验证流程画成一张图。

横着一条主线：**流程控制 → 设计与建模 → 验证构建 → 编译与仿真 →
覆盖率与调试 → 决策与收敛 → 审查与签核**，每块里列出它包含的阶段；
下面画一条**回边**，标出「不达标就再来一轮」——那是这个流程最要紧的形状，
摊平了看就没了。

**结构与状态分两路进来**：
  · `set_flow(model)` —— 流程长什么样。来自领域自己的 `stages.py`（经
    `flow.stages` 绑定），界面**不另抄一份阶段清单**。
  · `set_status(dict)` —— 每个阶段这次跑到什么状态（来自所选运行的日志）。
    没选运行时就是一片灰，不编造。

自绘而不是引图表库：与 `views/` 里其它件同一条纪律（见 `trend.py`）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme

MARGIN = 18            # 四周留白
GAP = 38               # 两块之间留给箭头的空当
BOX_W = 150            # 每块宽度（等宽，一行排下来才像流程）
HEADER_H = 24          # 块内标题条高度
ROW_H = 19             # 块内每个阶段占的高度
PAD = 8                # 块内上下留白
LOOP_H = 74            # 回边那一条占的高度

#: 每块最多列几个阶段 —— 决策与收敛那组有 12 个（大半是 apply_* 分支），
#: 全列出来会把整张图撑得没法看；超出的用「…还有 N 个」交代，**不静默吞掉**。
MAX_NODES_SHOWN = 5

#: 阶段状态 → 主题里的颜色字段。空/认不出 = 还没跑到，用弱色。
_STATUS_FIELD = {"ok": "ok", "passed": "ok", "running": "accent",
                  "failed": "error", "error": "error"}


class FlowMap(QWidget):
    """一张流程图。`set_flow` 给结构，`set_status` 给状态。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._groups: List[Dict[str, Any]] = []
        self._loop: Dict[str, str] = {}
        self._status: Dict[str, str] = {}
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def set_flow(self, model: Optional[Dict[str, Any]]) -> None:
        """整条流程的结构（阶段组 + 回边）。"""
        model = model or {}
        self._groups = list(model.get("groups") or [])
        self._loop = dict(model.get("loop") or {})
        self.updateGeometry()
        self.update()

    def set_status(self, status: Optional[Dict[str, str]] = None) -> None:
        """每个阶段这次的运行状态：`{stage_id: "ok"/"running"/"failed"}`。

        不给（或给了空）就是"还没选运行"—— 画成一片弱色，**不编造状态**。
        """
        self._status = dict(status or {})
        self.update()

    # ════════════════════════════════════════════════════════
    # 尺寸
    # ════════════════════════════════════════════════════════

    def _rows_per_box(self) -> int:
        """每块画几行 —— 等宽等高才像流程，所以取"最多那块"（封顶 `MAX_NODES_SHOWN`）。"""
        return max(1, min(MAX_NODES_SHOWN,
                          max((len(g.get("nodes") or []) for g in self._groups),
                              default=1)))

    def _box_height(self) -> int:
        rows = self._rows_per_box()
        # 有一块会被截断时多留一行放「…还有 N 个」
        extra = 1 if any(len(g.get("nodes") or []) > rows for g in self._groups) else 0
        return HEADER_H + (rows + extra) * ROW_H + PAD

    def sizeHint(self) -> QSize:
        n = max(1, len(self._groups))
        width = MARGIN * 2 + n * BOX_W + max(0, n - 1) * GAP
        return QSize(width, MARGIN * 2 + self._box_height() + LOOP_H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ════════════════════════════════════════════════════════
    # 绘制
    # ════════════════════════════════════════════════════════

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.current().panel))
        painter.setFont(theme.ui_font(9))
        metrics = QFontMetrics(theme.ui_font(9))

        if not self._groups:
            painter.setPen(theme.MUTED)
            painter.drawText(16, 28, "（还没有流程结构）")
            return

        boxes = self._layout_boxes()
        for index, (group, rect) in enumerate(boxes):
            self._draw_box(painter, group, rect, metrics)
            if index:                                # 块与块之间的箭头
                self._draw_arrow(painter, boxes[index - 1][1], rect)
        self._draw_loop(painter, boxes)

    def _layout_boxes(self) -> List[Tuple[Dict[str, Any], QRect]]:
        height = self._box_height()
        out = []
        for index, group in enumerate(self._groups):
            x = MARGIN + index * (BOX_W + GAP)
            out.append((group, QRect(x, MARGIN, BOX_W, height)))
        return out

    def _draw_box(self, painter: QPainter, group: Dict[str, Any],
                  rect: QRect, metrics: QFontMetrics) -> None:
        palette = theme.current()
        # 整块的底色按"这组里最坏的那个状态"走：有一处失败就整块标红 ——
        # 扫一眼就知道卡在哪一段，不用逐行读。
        agg = self._aggregate(group)
        painter.setPen(QPen(QColor(self._field_color(agg)), 1))
        painter.setBrush(QColor(palette.panel_alt))
        painter.drawRect(rect)

        # 标题条
        header = QRect(rect.left(), rect.top(), rect.width(), HEADER_H)
        painter.fillRect(header, QColor(self._field_color(agg, soft=True)))
        painter.setPen(QColor(palette.text))
        bold = theme.ui_font(9, bold=True)
        painter.setFont(bold)
        painter.drawText(header.adjusted(6, 0, -6, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         metrics.elidedText(str(group.get("title", "")),
                                            Qt.TextElideMode.ElideRight,
                                            header.width() - 12))
        painter.setFont(theme.ui_font(9))

        # 成员阶段
        nodes = list(group.get("nodes") or [])
        shown = nodes[:MAX_NODES_SHOWN]
        y = rect.top() + HEADER_H + PAD // 2
        for node in shown:
            status = self._status.get(str(node.get("id", "")), "")
            dot = QRect(rect.left() + 8, y + ROW_H // 2 - 3, 6, 6)
            painter.setBrush(QColor(self._field_color(status)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(dot)
            painter.setPen(QColor(palette.muted if not status else palette.text))
            painter.drawText(QRect(rect.left() + 20, y, rect.width() - 26, ROW_H),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             metrics.elidedText(str(node.get("title", "")),
                                                Qt.TextElideMode.ElideRight,
                                                rect.width() - 26))
            y += ROW_H
        if len(nodes) > len(shown):
            # 截断要记账 —— 静默吞掉会让人以为这组就只有这么几个阶段
            painter.setPen(QColor(palette.muted))
            painter.drawText(QRect(rect.left() + 20, y, rect.width() - 26, ROW_H),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             f"…还有 {len(nodes) - len(shown)} 个")
        painter.setPen(QPen(QColor(palette.border), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_arrow(self, painter: QPainter, left: QRect, right: QRect) -> None:
        """两块之间的右向箭头。"""
        y = left.top() + left.height() // 2
        x1, x2 = left.right() + 4, right.left() - 4
        painter.setPen(QPen(QColor(theme.current().border), 2))
        painter.drawLine(QPointF(x1, y), QPointF(x2 - 6, y))
        painter.setBrush(QColor(theme.current().border))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([QPointF(x2, y), QPointF(x2 - 8, y - 4),
                                       QPointF(x2 - 8, y + 4)]))

    def _draw_loop(self, painter: QPainter, boxes) -> None:
        """那条回边 —— 「不达标就再来一轮」。**这是流程最要紧的形状。**"""
        by_id = {g.get("id"): rect for g, rect in boxes}
        src = by_id.get(str(self._loop.get("from", "")))
        dst = by_id.get(str(self._loop.get("to", "")))
        if src is None or dst is None:
            return
        palette = theme.current()
        y = src.bottom() + LOOP_H // 2
        painter.setPen(QPen(QColor(palette.accent), 2, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # 从左块的底边下去，横着拉回右块的底边，再上去
        painter.drawLine(QPointF(src.center().x(), src.bottom() + 3),
                         QPointF(src.center().x(), y))
        painter.drawLine(QPointF(src.center().x(), y), QPointF(dst.center().x(), y))
        painter.drawLine(QPointF(dst.center().x(), y),
                         QPointF(dst.center().x(), dst.bottom() + 3))
        # 箭头指向"往上回到那一块"
        painter.setBrush(QColor(palette.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        cx = dst.center().x()
        painter.drawPolygon(QPolygonF([QPointF(cx, dst.bottom() + 2),
                                       QPointF(cx - 4, dst.bottom() + 10),
                                       QPointF(cx + 4, dst.bottom() + 10)]))
        painter.setPen(QColor(palette.accent))
        painter.drawText(QRect(min(src.center().x(), dst.center().x()), y - 18,
                               abs(src.center().x() - dst.center().x()), 16),
                         Qt.AlignmentFlag.AlignCenter, "未达标 → 再来一轮")

    # ── 颜色 ──

    def _aggregate(self, group: Dict[str, Any]) -> str:
        """这一组的状态：**最坏优先**（有 failed 就 failed，其次 running，再其次 ok）。"""
        seen = [self._status.get(str(n.get("id", "")), "")
                for n in (group.get("nodes") or [])]
        for want in ("failed", "error", "running", "ok", "passed"):
            if want in seen:
                return want
        return ""

    @staticmethod
    def _field_color(status: str, *, soft: bool = False) -> str:
        palette = theme.current()
        field = _STATUS_FIELD.get(status, "")
        if not field:
            return palette.panel_alt if soft else palette.muted
        color = getattr(palette, field)
        # 底色要压淡 —— 直接铺满会把上面的字盖掉
        return QColor(color).lighter(165).name() if soft else color
