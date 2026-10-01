"""表现层 —— 只把 AnalysisResult 摆成可读的形状，不含任何判定逻辑。

    text.py          纯文本（CLI）
    widgets.py       tkinter 可复用控件
    gui/app.py       主窗口
    gui/tabs/*.py    每个标签页一个组件

之所以把 GUI 也放在「表现」层，是因为它和文本渲染读的是同一份
AnalysisResult —— 两边不会各算一套、各说各话。
"""
from __future__ import annotations

from . import text

__all__ = ["text"]
