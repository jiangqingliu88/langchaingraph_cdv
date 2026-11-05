"""顶部提示条 —— 「当前这份文本构不出模型」这一类必须让人看见的消息。

为什么不用 QMessageBox：弹窗要求点一下才能继续，而**改到一半的模型构不出
结构**是编辑过程中的常态。弹窗会把人逼疯，横幅不会 —— 它挂在顶上，改好了
自己消失。

三条规则（都是从旧 casemodel 界面沿用的，踩过坑）：
  · 清空时要**连文本一起清**，不能只 `setVisible(False)` —— 否则下一次
    读取会拿到陈旧内容，出现「已经修好了却还显示旧错误」。
  · 三种语气（error / warning / info）各自有底色与前景，不要只改文字。
  · 横幅不参与布局高度计算 —— 隐藏时 `QVBoxLayout` 会把它收起来。

底色与前景取自**当前调色板**（`banner_<语气>_bg/_fg`）。早先这三对是写死的
浅色 —— 深色主题下横幅就是一块惨白的盒子，比它要提示的错误还扎眼。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLabel, QWidget

from ..theme import palette as theme

#: 三种语气
KINDS = ("error", "warning", "info")


def _colors(kind: str) -> tuple:
    """语气 → (底, 字)。认不出的语气按 info 处理，不抛。"""
    return theme.current().banner_colors(kind if kind in KINDS else "info")


class Banner(QLabel):
    """一行可换行的提示条。空消息 = 收起。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setVisible(False)
        self._kind = "info"
        #: 当前用的这对色 —— 测试与自查读它，不必去解析样式表
        self._background, self._foreground = _colors("info")

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def colors(self) -> tuple:
        """当前 (底, 字)。切主题后这里还是旧值，直到下次 `show_message`。"""
        return (self._background, self._foreground)

    def show_message(self, text: str, kind: str = "info") -> None:
        """显示一条消息。空 text 等价于 `clear_message()`。"""
        if not text:
            self.clear_message()
            return
        background, foreground = _colors(kind)
        self._kind = kind if kind in KINDS else "info"
        self.setStyleSheet(f"background: {background}; color: {foreground};"
                           f"padding: 6px; border-radius: 3px;")
        self.setText(text)
        self.setVisible(True)
        self._background, self._foreground = background, foreground

    def clear_message(self) -> None:
        """收起横幅。**同时清文本** —— 只隐藏会让下次读到陈旧内容。"""
        self.setText("")
        self.setVisible(False)

    @property
    def is_showing(self) -> bool:
        """是否正在显示。

        判据是 `isHidden()` 而不是 `isVisible()`：窗口自己没 `show()` 时
        （offscreen 测试、或者窗口还没显示出来），子控件的 `isVisible()` 一律
        是 False，哪怕它被显式设成了可见 —— `isHidden()` 只反映「是不是被
        显式藏起来的」，正是这里要问的问题。
        """
        return (not self.isHidden()) and bool(self.text())


class PermanentNote(Banner):
    """常驻横幅 —— 给「演示数据，未接真实数据源」这类**不许被关掉**的说明。

    与 Banner 的差别只有一个：`clear_message()` 是空操作。之所以要这个类，
    是因为占位视图最容易被误当成「功能坏了/功能好了」，一条能被人习惯性
    无视的提示等于没有提示。
    """

    def __init__(self, text: str = "", kind: str = "warning",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        if text:
            self.show_message(text, kind)

    def clear_message(self) -> None:                 # noqa: D102  —— 故意的空实现
        return
