"""中央工作区 —— 视图以「子窗口」承载的那块区域。

**这一层只管中央**：它怎么排版、标签栏长什么样、空了显示什么、窗口怎么收放。
谁属于哪个模块、显隐状态记在哪、布局怎么落盘 —— 那些是 `Workspace` 的事。

排版默认是 **标签页模式（VSCode 那种）**：一次开多个、顶部一条标签栏点着切，
而不是一堆漂浮的子窗口（那个很快就乱了）。视图菜单可切到子窗口模式去并排。

**标签锁死、拖不动** —— 拖拽会把标签拽成一个浮在工作区里的子窗口，
那正是"页面自己独立出来"，不是我们要的（要独立窗口的走 dock 那套）。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QMdiArea, QMdiSubWindow, QTabBar

from ...theme import palette as theme
from .empty_state import EmptyState
from .subwindow import DEFAULT_SIZE, ModuleSubWindow


class WorkspaceArea(QMdiArea):
    """中央那块 —— 子窗口的容器 + 它的排版与空态。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("mdiArea")

        # 默认标签页模式，理由见模块说明
        self.setViewMode(QMdiArea.ViewMode.TabbedView)
        # 扁平标签栏 —— documentMode 是"这是文档页签"的那套观感
        self.setDocumentMode(True)
        # **每个标签带 ×** —— 不打开它，标签上就没有关闭按钮，只能去「窗口」
        # 菜单里找那个勾选项，很不直观。
        #
        # 不用自己接信号：Qt 的 `QMdiArea` 内部已经把标签栏的关闭请求接到了
        # 子窗口的 `close()`，于是自然走到 `ModuleSubWindow.closeEvent`
        # （守卫 + 摘标签那条路）。`QMdiArea` 本身**没有** `tabCloseRequested`
        # 信号 —— 那是 `QTabWidget` 的，别混。
        self.setTabsClosable(True)
        self.setTabsMovable(False)
        self.setActivationOrder(QMdiArea.WindowOrder.ActivationHistoryOrder)
        # "激活时铺满"这个开关**跟着视图模式走**，见 `_sync_maximize_option`。
        self._sync_maximize_option()

        self._empty = EmptyState(self)
        self.apply_theme()
        self.sync_chrome()

    def apply_theme(self) -> None:
        """把"工作区底色"刷成当前主题的内容色 —— 换主题时由窗口调。

        **必须显式设，QSS 管不到这块**：`QMdiArea` 画背景用的是它自己的
        `background()` 画刷，而那个画刷来自 `QPalette::Dark`，跟全局样式表
        是两套东西。不设的话它在两套主题下**都是 Qt 默认的 #9f9f9f** ——
        浅色主题下是一块比周围暗的方板，深色主题下更糟，整块惨白地杵在
        深色界面正中间。实测过：加一条 `QMdiArea { background: … }` 也走不到这里。
        """
        self.setBackground(QBrush(QColor(theme.current().panel)))
        self._empty.apply_theme()

    def _sync_empty_size(self) -> None:
        """让引导文字铺满整块工作区（它靠对齐居中，铺满是前提）。

        入口有三处 —— 建好、尺寸变了、子窗口数变了 —— 都收到这里，
        免得三处各差一个条件。**不带 `isVisible()` 守卫**：窗口第一次铺开
        时子控件还没 `show()`，带守卫会让这次唯一的 resize 被跳过。
        """
        self._empty.follow_size(self.viewport().width(),
                                self.viewport().height())

    # ════════════════════════════════════════════════════════
    # 窗口收放
    # ════════════════════════════════════════════════════════

    def attach(self, sub: ModuleSubWindow) -> None:
        """把一个子窗口挂进工作区 —— 新开的走这儿。"""
        count = len(self.subWindowList())
        self.addSubWindow(sub)
        sub.resize(*DEFAULT_SIZE)
        if count:
            # 第二个起错位摆一下，免得正好盖住上一个
            step = 24 * count
            sub.move(step, step)
        sub.show()
        self.sync_chrome()

    def detach(self, sub: QMdiSubWindow) -> None:
        """**摘出去**而不是 `setVisible(False)`。

        后者在标签页模式下标签仍然挂在标签栏里，看着像关不掉。控件本身留着
        （引用在 `Workspace` 里），所以模块状态不丢 —— 随时能从导航树再开。
        """
        self.removeSubWindow(sub)
        # 摘下来之后它就成了**独立的顶层窗口**（不可见，但活着）—— 挂回窗口
        # 做隐藏子件。不挂的话：界面上悄悄攒着一堆看不见的顶层窗口，主窗口关了
        # 它们还拖着进程（实测过：退出时仍有一个可见的顶层窗口）。
        top = self.window()               # 顶层窗口（不是 `self.window` 属性）
        if top is not self:
            # 守卫：**area 自己就是顶层控件时别往回挂** —— `window()` 会返回
            # 它自己，那样 `setParent` 等于把子窗口又塞回 MDI 里（`subWindowList()`
            # 立刻不为空）。真窗口里 area 在 QMainWindow 之内，这条永远成立。
            sub.setParent(top)
        sub.hide()
        self.sync_chrome()

    def reattach(self, sub: QMdiSubWindow) -> None:
        """把先前摘出去的窗口放回来。"""
        if sub not in self.subWindowList():
            self.addSubWindow(sub)
        sub.show()
        self.sync_chrome()

    def close_all(self) -> None:
        """清空（重载清单等场景用）。"""
        for sub in list(self.subWindowList()):
            self.removeSubWindow(sub)
        self.sync_chrome()

    # ════════════════════════════════════════════════════════
    # 查询
    # ════════════════════════════════════════════════════════

    def subwindows_in_order(self) -> List[QMdiSubWindow]:
        """按**创建顺序**排的子窗口。

        必须显式要 `CreationOrder` —— `subWindowList()` 默认给的是**层叠顺序**
        （最后激活的在最前），拿它当"清单顺序"会随用户点哪一下而变。
        """
        return list(self.subWindowList(QMdiArea.WindowOrder.CreationOrder))

    def active_module_id(self) -> str:
        """当前聚焦的子窗口属于哪个模块（没聚焦任何子窗口就是空串）。"""
        sub = self.activeSubWindow()
        return str(sub.property("module_id") or "") if sub is not None else ""

    def window_count(self) -> int:
        return len(self.subWindowList())

    def is_empty(self) -> bool:
        """一个视图窗口都没开 —— "空态"的判据只此一处。"""
        return not self.subWindowList()

    @property
    def empty_hint(self) -> EmptyState:
        """空态提示控件。给测试与自查用 —— 别的地方不该碰它。"""
        return self._empty

    # ════════════════════════════════════════════════════════
    # 排版（「窗口」菜单用）
    # ════════════════════════════════════════════════════════

    def tile(self) -> None:
        """平铺。**标签页模式下先切回子窗口模式** —— 标签页里"平铺"没有意义，
        点了却什么都不发生会让人以为按钮坏了。"""
        self._ensure_subwindow_view()
        self.tileSubWindows()

    def cascade(self) -> None:
        """层叠。同上，先切回子窗口模式。"""
        self._ensure_subwindow_view()
        self.cascadeSubWindows()

    def activate_next(self) -> None:
        self.activateNextSubWindow()

    def set_view_mode(self, tiled: bool) -> None:
        """平铺视图 = Qt 自己的 TabbedView（子窗口铺成标签页）。"""
        self.setViewMode(QMdiArea.ViewMode.TabbedView if tiled
                         else QMdiArea.ViewMode.SubWindowView)
        self._sync_maximize_option()

    def _sync_maximize_option(self) -> None:
        """「激活时是否让当前窗口铺满」—— **跟着视图模式走**。

        标签页模式**必须**铺满：Qt 就是靠"当前那个占满整块区域"来实现
        "一次只显示一个"的。这里若禁止最大化，子窗口会保持各自的层叠尺寸、
        连标题栏一起露出来 —— 界面上就是"一条标签栏 + 底下几个带 ✕ 的小窗口"
        叠在一起，**根本不像多文件编辑器的标签**（真踩过）。

        子窗口模式反过来：不禁止的话，点一下就把窗口撑满，"并排比较"就没了。
        """
        self.setOption(QMdiArea.AreaOption.DontMaximizeSubWindowOnActivation,
                       not self.is_tiled_view())

    def is_tiled_view(self) -> bool:
        return self.viewMode() == QMdiArea.ViewMode.TabbedView

    def _ensure_subwindow_view(self) -> None:
        if self.is_tiled_view():
            self.set_view_mode(False)

    # ════════════════════════════════════════════════════════
    # 空态与标签栏
    # ════════════════════════════════════════════════════════

    def sync_chrome(self) -> None:
        """子窗口数变了之后重算"外观"：空态提示 + 那条空标签栏。

        空标签栏不藏的话，顶上会留一条什么都没有的标签栏 —— 那是"看起来像坏了"。
        """
        empty = self.is_empty()
        self._empty.set_empty(empty)
        if empty:
            self._sync_empty_size()
        # **只动 MDI 自己那条标签栏** —— `findChildren` 默认是递归的，会把模块
        # **内部**的标签栏（case 建模 11 页、运行清单的"文件变更链"…）一起捞进来，
        # 于是"空态藏标签栏"会把人家模块内部的页签也藏掉。MDI 的标签栏是
        # `QMdiArea` 的直接子级，限定到这一层才安全。
        for bar in self.findChildren(
                QTabBar, options=Qt.FindChildOption.FindDirectChildrenOnly):
            bar.setVisible(not empty)
            # **标签按内容宽度排、左对齐** —— Qt 默认是 `expanding`（每个标签
            # 平分整条标签栏），那样开/关一个标签所有标签的宽度都会变，而且
            # 几个标签就把整条铺满 —— 完全不是编辑器那种"文件名大小的标签、
            # 右边留空"的手感（VSCode / 浏览器都是这样）。真被问过"怎么不像
            # VSCode 切页面"。
            bar.setExpanding(False)

    def resizeEvent(self, event) -> None:                # noqa: N802  Qt 接口
        """尺寸变了 —— 引导文字跟着铺满。"""
        super().resizeEvent(event)
        self._sync_empty_size()

    def showEvent(self, event) -> None:                  # noqa: N802  Qt 接口
        """第一次显示 —— 补一次铺满。

        `resizeEvent` 在窗口铺开时可能比 `show()` 早，那一瞬间尺寸已经是对的、
        但"显示过一次"这件事还没发生。空态是**窗口一起来就该居中**的，
        不能等用户拖一下窗口才归位。
        """
        super().showEvent(event)
        self._sync_empty_size()
