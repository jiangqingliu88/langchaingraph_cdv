"""容器 —— 决定"东西摆在哪"的那一类（停靠面板、可停靠/可浮动的面板）。

与 `ui/widgets` 的区别：那边的件只管自己的内容，这边的件管**别人的位置**。
"""
from . import workspace

__all__ = ["workspace"]
