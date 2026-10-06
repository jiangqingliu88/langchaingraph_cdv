"""空工作区的引导 —— 工作区一个视图都没开时露出来的那句话。

**空不是"一片空白"**：跟 VSCode 打开时的欢迎页一个意思，告诉人"从这里开始"，
而不是让人对着空窗格发呆。它是 `WorkspaceArea` 的子控件，由 area 统一决定
什么时候露出来（见 `WorkspaceArea.sync_chrome`）。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from ...theme import palette as theme

#: 引导文案。改口径只改这一处。
TEXT = ("工作区是空的\n\n"
        "从左边的「模块导航树」双击一个视图，它就开在这里。\n"
        "开多个 = 多条标签，点标签切换；关掉标签不丢状态，随时能再打开。")


class EmptyState(QLabel):
    """空态提示条 —— 只管"显示什么、什么时候显"，不管谁来铺满。"""

    #: 引导文案（类属性，方便调用方/测试按类问）
    TEXT = TEXT

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(TEXT, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        # **不吃鼠标**：它盖满整个工作区，不设这一条的话，空工作区上的右键
        # 菜单、框选就全被这块文字挡掉了。
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.apply_theme()

    def apply_theme(self) -> None:
        """按当前主题重刷文字色 —— 换主题时由工作区调。

        颜色只能走 `setStyleSheet`（QSS 里的 `QLabel` 规则是通配的，压不住
        这里的 `color`）。所以它不是"设一次就不管"的：主题一换就得重来，
        否则深色主题下留着一行浅灰的字，糊在深底上。
        """
        self.setStyleSheet(f"color: {theme.current().muted};")

    def set_empty(self, empty: bool) -> None:
        """工作区空/不空 —— 决定这句提示露不露。"""
        self.setVisible(empty)

    def follow_size(self, width: int, height: int) -> None:
        """贴着工作区铺满 —— 文字靠 `AlignCenter` 居中，所以**必须先铺满**。

        早先这里只在 `resizeEvent` 里调，而 `resizeEvent` 带着
        `if self._empty.isVisible()` 的守卫：窗口第一次铺开时它还没 `show()`，
        `isVisible()` 是 False，于是这句 resize **一次都没执行过** —— 标签停在
        构造时的 100×30、坐标 (0,0)，引导文字就缩在左上角。铺满是居中的前提，
        不是可有可无的装饰。
        """
        self.setGeometry(0, 0, width, height)
        self.raise_()
