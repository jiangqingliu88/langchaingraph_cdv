"""通用控件 —— 「一块内容」这一级的小件（横幅、面板、控制台、占位画布）。

它们不依赖任何业务词汇，只依赖 `ui/theme`（外观）与 `ui/models`（数据）。
"""
from .banner import Banner, PermanentNote
from .console import ConsolePanel
from .panels import IssuePanel, RowsPanel
from .placeholder import DemoCanvas, PaintedPlaceholder

__all__ = ["Banner", "PermanentNote", "ConsolePanel",
           "IssuePanel", "RowsPanel", "DemoCanvas", "PaintedPlaceholder"]
