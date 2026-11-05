"""自绘视图 —— 用 `QPainter` 在 `paintEvent` 里画出来的那些件。

本仓库不引图表库（见 `trend_chart` 的说明）：自绘没有依赖、配色跟主题走、
字体与 DPI 也可控。这一层就是"把数据画成图形"的那部分。
"""
from .coverage import CoverageView
from .flowmap import FlowMap
from .matrix import MatrixView
from .trend import SERIES_COLORS, TrendChart

__all__ = ["CoverageView", "MatrixView", "TrendChart", "SERIES_COLORS",
           "FlowMap"]
