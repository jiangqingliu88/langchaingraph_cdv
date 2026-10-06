"""工作区拆出来的几个**界面元素**，各自单独测。

`test_workspace.py` 测的是 `Workspace` 这个门面（组装后的行为）；这里测的是
零件本身 —— 能这么测，正是把它们拆出来的意义：不用建整个工作区、不用起窗口，
就能验一个元素自己的规矩。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDockWidget, QLabel, QMainWindow, QMdiArea,
                               QTabBar, QWidget)

from ..ui.containers.workspace import EmptyState, ModuleDock, ModuleSubWindow, WorkspaceArea


class TestModuleSubWindow:
    """一个视图窗口：带三件套按钮、关之前问守卫、关掉不销毁。"""

    def test_carries_its_module_id(self, qt_app):
        sub = ModuleSubWindow("flow.task", "任务总览", QLabel("x"))
        assert sub.module_id == "flow.task"
        assert sub.objectName() == "subwindow.flow.task"

    def test_has_minimize_maximize_close_buttons(self, qt_app):
        sub = ModuleSubWindow("a", "甲", QLabel("x"))
        flags = sub.windowFlags()
        assert flags & Qt.WindowType.WindowMinimizeButtonHint
        assert flags & Qt.WindowType.WindowMaximizeButtonHint
        assert flags & Qt.WindowType.WindowCloseButtonHint

    def test_closing_does_not_destroy_it(self, qt_app):
        """关掉只是隐藏 —— 模块状态不该因为关一下就没了。"""
        sub = ModuleSubWindow("a", "甲", QLabel("x"))
        assert not (sub.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))

    def test_guard_can_refuse_the_close(self, qt_app):
        sub = ModuleSubWindow("a", "甲", QLabel("x"), guard=lambda _m: False)
        sub.show()
        sub.close()
        assert not sub.isHidden()          # 被守卫拦下了

    def test_guard_lets_it_through_to_the_callback(self, qt_app):
        """守卫过了之后**不交给 Qt 自己收** —— 走回调，让工作区正规地摘标签。"""
        seen = []
        sub = ModuleSubWindow("a", "甲", QLabel("x"),
                              guard=lambda _m: True, on_closed=seen.append)
        sub.show()
        sub.close()
        assert seen == ["a"]

    def test_a_previously_hidden_widget_gets_shown(self, qt_app):
        """**承进来的控件要清掉"隐藏"状态。**

        中心模块的控件在懒加载时是被 `hide()` 挂着的（没点开就不该露面）。
        `setWidget` 只重挂父级、**不清隐藏状态** —— 不清的话子窗口里一片空白，
        而且 Qt 布局会跳过隐藏子件，控件尺寸还卡在 640×480 不跟着缩放。
        表现就是"每页内容都是空的/不全"（真踩过，渲染出图才看见）。
        """
        page = QLabel("x")
        page.hide()
        sub = ModuleSubWindow("a", "甲", page)
        assert page.isVisibleTo(sub)

    def test_take_widget_hands_the_widget_back(self, qt_app):
        widget = QLabel("x")
        sub = ModuleSubWindow("a", "甲", widget)
        assert sub.take_widget() is widget
        assert sub.widget() is None


@pytest.fixture
def host(qt_app):
    """Dock 的宿主窗口 —— **必须留个引用**：临时 QMainWindow 会被 GC 掉，
    它带的 dock 跟着一起删（报 `Internal C++ object already deleted`）。"""
    window = QMainWindow()
    yield window
    window.deleteLater()


class TestModuleDock:
    """一个侧栏面板：能拖、能浮、能关、能停任意边。"""

    def test_is_movable_floatable_closable(self, qt_app, host):
        dock = ModuleDock("flow.runs", "运行历史", QLabel("x"), host)
        features = dock.features()
        assert features & QDockWidget.DockWidgetFeature.DockWidgetMovable
        assert features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert features & QDockWidget.DockWidgetFeature.DockWidgetClosable

    def test_can_dock_to_any_area(self, qt_app, host):
        dock = ModuleDock("a", "甲", QLabel("x"), host)
        assert dock.allowedAreas() == Qt.DockWidgetArea.AllDockWidgetAreas

    def test_carries_its_module_id(self, qt_app, host):
        dock = ModuleDock("flow.runs", "运行历史", QLabel("x"), host)
        assert dock.module_id == "flow.runs"
        assert dock.objectName() == "dock.flow.runs"

    def test_title_can_be_rewritten(self, qt_app, host):
        dock = ModuleDock("a", "甲", QLabel("x"), host)
        dock.set_title("甲 ●")
        assert dock.windowTitle() == "甲 ●"


class TestEmptyState:
    def test_shows_and_hides_by_flag(self, qt_app):
        state = EmptyState()
        state.show()
        state.set_empty(False)
        assert not state.isVisible()
        state.set_empty(True)
        assert state.isVisible()

    def test_text_tells_you_where_to_start(self, qt_app):
        assert "模块导航树" in EmptyState.TEXT
        assert "双击" in EmptyState.TEXT

    def test_follow_size_actually_fills_and_centres(self, qt_app):
        """铺满是**居中的前提**，不是装饰。

        回归：`follow_size` 原先只在 `resizeEvent` 里、还带着
        `if self._empty.isVisible()` 的守卫。窗口第一次铺开时子控件还没
        `show()`，那次唯一的 resize 被跳过 —— 标签停在构造时的 100×30、
        坐标 (0,0)，引导文字就一直缩在工作区左上角。
        """
        state = EmptyState()
        state.follow_size(400, 300)
        assert state.geometry().getRect() == (0, 0, 400, 300)

    def test_text_colour_follows_the_theme(self, qt_app):
        """颜色只能走 `setStyleSheet`，所以它不是"设一次就不管"的 ——
        主题一换就得重刷，否则深色底上留着一行浅灰的字。

        **切配色传 `None`，不传 `qt_app`**：这条测的是 `EmptyState` 有没有
        **重读当前配色**，不是"全局重刷干不干净"。传 app 会触发
        `QApplication.setStyleSheet`，那会遍历进程里**每一个**控件 ——
        包括前面几百个用例留下的、Python 侧已经回收而 Qt 侧还挂着的顶层控件，
        于是随机一个 access violation（整个文件单独跑是绿的，跑全量才炸）。
        顺带也快得多：全局重刷一遍样式表是秒级的。
        """
        from ..ui import theme

        original = theme.current().name
        state = EmptyState()
        try:
            theme.apply(None, theme.CLASSIC.name)
            state.apply_theme()                # 换主题时工作区喊的那一声
            light = state.styleSheet()
            theme.apply(None, theme.DARK.name)
            state.apply_theme()
            dark = state.styleSheet()
        finally:
            theme.apply(None, original)
        assert light != dark


class TestDockVisibilityIsSingleSourceOfTruth:
    """dock 的显隐**问它自己**，不另记一份 —— 少一份状态就少一处能对不上的地方。

    来历：Qt 也有一条关掉 dock 的路（右键 dock 时 `QMainWindow.createPopupMenu()`
    给的勾选项，直接 `hide()`、不经平台）。自己再记一份的话，面板没了而记账还
    写着"开着"——「窗口」菜单的勾照旧亮着，再点它要两下才回来，表现就是
    "右键 Close 关不掉"（真踩过）。判据用 `isHidden()`：它只反映"是否被显式隐藏"，
    不受父窗口有没有 show 影响（那正是 `isVisible()` 的坑）。
    """

    @staticmethod
    def _workspace_with_dock(qt_app):
        from ..ui.containers.workspace import ModuleDock, Workspace
        window = QMainWindow()
        ws = Workspace(window, close_guard=lambda _m: True)
        window.setCentralWidget(ws.mdi)
        dock = ModuleDock("a", "甲", QLabel("x"), window)
        ws.add_module(QLabel("x"), "甲", "a", "left")
        window.show()
        qt_app.processEvents()
        return ws, window

    def test_a_dock_is_open_right_after_being_added(self, qt_app):
        ws, _w = self._workspace_with_dock(qt_app)
        assert ws.contains("a")

    def test_qt_side_close_is_reflected(self, qt_app):
        """Qt 自己把 dock hide 掉（不经平台）—— 平台要认得出来。"""
        ws, _w = self._workspace_with_dock(qt_app)
        ws.dock_of("a").hide()
        qt_app.processEvents()
        assert not ws.contains("a")

    def test_reopen_after_qt_side_close_takes_one_call(self, qt_app):
        """从菜单再打开应当**一次**就回来。"""
        ws, _w = self._workspace_with_dock(qt_app)
        ws.dock_of("a").hide()
        qt_app.processEvents()
        assert ws.set_module_visible("a", True) is True
        assert ws.contains("a")

    def test_visibility_change_notifies_the_outside(self, qt_app):
        """dock 实际显隐变了要通知外部 —— 「窗口」菜单那段勾靠它同步。"""
        ws, _w = self._workspace_with_dock(qt_app)
        seen = []
        ws.on_visibility_changed = lambda mid, vis: seen.append((mid, vis))
        ws.dock_of("a").hide()
        qt_app.processEvents()
        assert ("a", False) in seen


class TestDockTabClose:
    """停靠区那条标签栏也要有 × —— 不然关一个面板只能右键绕，用户以为"关不掉"。"""

    @staticmethod
    def _win(qt_app):
        from ..ui.containers.workspace import Workspace
        window = QMainWindow()
        ws = Workspace(window, close_guard=lambda _m: True)
        window.setCentralWidget(ws.mdi)
        ws.add_module(QLabel("nav"), "模块", "__nav__", "left")
        ws.add_module(QLabel("runs"), "运行历史", "runs", "left")
        window.show()
        qt_app.processEvents()
        return ws, window

    @staticmethod
    def _dock_bar(window, title):
        for bar in window.findChildren(QTabBar):
            if bar.parent() is window and title in [bar.tabText(i)
                                                    for i in range(bar.count())]:
                return bar
        return None

    def test_dock_tabs_are_closable(self, qt_app):
        _ws, window = self._win(qt_app)
        bar = self._dock_bar(window, "运行历史")
        assert bar is not None and bar.tabsClosable()

    def test_every_dock_tab_has_a_close_button(self, qt_app):
        _ws, window = self._win(qt_app)
        bar = self._dock_bar(window, "运行历史")
        for index in range(bar.count()):
            assert bar.tabButton(index, QTabBar.ButtonPosition.RightSide) is not None

    def test_clicking_the_x_closes_that_panel(self, qt_app):
        ws, window = self._win(qt_app)
        bar = self._dock_bar(window, "运行历史")
        index = [i for i in range(bar.count()) if bar.tabText(i) == "运行历史"][0]
        bar.tabButton(index, QTabBar.ButtonPosition.RightSide).click()
        qt_app.processEvents()
        assert not ws.contains("runs")

    def test_a_pinned_dock_cannot_be_closed_from_its_tab(self, qt_app):
        """导航树 / 控制台关不掉 —— 与「视图」菜单同一口径。"""
        ws, window = self._win(qt_app)
        ws.add_pinned(QLabel("console"), "控制台", "__console__", "left")
        qt_app.processEvents()
        bar = self._dock_bar(window, "控制台")
        index = [i for i in range(bar.count()) if bar.tabText(i) == "控制台"][0]
        bar.tabButton(index, QTabBar.ButtonPosition.RightSide).click()
        qt_app.processEvents()
        assert ws.contains("__console__")


class TestWorkspaceArea:
    """中央那块：自配置 + 空态 + 创建序。"""

    def test_starts_tabbed_closable_and_locked(self, qt_app):
        area = WorkspaceArea()
        assert area.viewMode() == QMdiArea.ViewMode.TabbedView
        assert area.tabsClosable()
        assert not area.tabsMovable()          # 锁死：标签拖不出去
        assert area.documentMode()

    def test_starts_empty_with_the_hint_showing(self, qt_app):
        area = WorkspaceArea()
        area.show()
        qt_app.processEvents()
        assert area.is_empty()
        assert area.empty_hint.isVisible()

    def test_backdrop_follows_the_theme(self, qt_app):
        """工作区底色必须跟着主题走 —— **QSS 到不了这里**。

        回归：`QMdiArea` 画底用的是它自己构造时从 `QPalette::Dark` 抓的一份
        快照（`background()` 画刷），全局样式表改不动它。不显式设的话它**在
        两套主题下都是 Qt 默认的 `#9f9f9f`** —— 浅色主题下一块比周围暗的方板，
        深色主题下整块惨白地杵在正中间。实测过 `QMdiArea {{ background: … }}`
        这条 QSS 也走不到。
        """
        from ..ui import theme

        original = theme.current().name
        try:
            theme.apply(None, theme.CLASSIC.name)
            area = WorkspaceArea()
            assert area.background().color().name() == theme.CLASSIC.panel

            theme.apply(None, theme.DARK.name)
            area.apply_theme()                 # 窗口换主题时喊的就是这一声
            assert area.background().color().name() == theme.DARK.panel
        finally:
            theme.apply(None, original)

    def test_hint_fills_the_area_once_shown(self, qt_app):
        """空态提示要**铺满**整块工作区 —— 文字靠对齐居中，铺满是前提。"""
        area = WorkspaceArea()
        area.resize(500, 400)
        area.show()
        qt_app.processEvents()
        assert area.empty_hint.size() == area.viewport().size()

    def test_attach_hides_the_hint(self, qt_app):
        area = WorkspaceArea()
        area.show()
        area.attach(ModuleSubWindow("a", "甲", QLabel("x")))
        assert not area.is_empty()
        assert not area.empty_hint.isVisible()

    def test_detach_brings_the_hint_back(self, qt_app):
        area = WorkspaceArea()
        area.show()
        sub = ModuleSubWindow("a", "甲", QLabel("x"))
        area.attach(sub)
        area.detach(sub)
        assert area.is_empty()
        assert area.empty_hint.isVisible()

    def test_attached_view_fills_its_window(self, qt_app):
        """视图要**铺满**它所在的那个窗口 —— 不铺满就是"内容不全"。"""
        area = WorkspaceArea()
        area.resize(820, 520)
        area.show()
        page = QLabel("x")
        area.attach(ModuleSubWindow("a", "甲", page))
        qt_app.processEvents()
        sub = area.subwindows_in_order()[0]
        assert page.width() == sub.width()
        assert page.height() == sub.height()

    def test_subwindows_in_order_is_creation_order(self, qt_app):
        area = WorkspaceArea()
        area.show()
        for mid in ("a", "b", "c"):
            area.attach(ModuleSubWindow(mid, mid, QLabel("x")))
        area.setActiveSubWindow(area.subwindows_in_order()[0])   # 聚焦第一个
        assert [s.module_id for s in area.subwindows_in_order()] == ["a", "b", "c"]

    def test_tabs_are_content_sized_not_stretched(self, qt_app):
        """**标签按内容宽度排、左对齐** —— 这才是编辑器的手感。

        Qt 默认 `expanding=True`：每个标签平分整条标签栏。那样开/关一个标签，
        其余标签的宽度全跟着变，而且几个标签就把整条铺满 —— 完全不像 VSCode /
        浏览器那种"文件名大小的标签、右边留空"（真被问过"怎么不像 VSCode"）。
        """
        area = WorkspaceArea()
        area.resize(900, 500)
        area.show()
        for mid in ("a", "b"):
            area.attach(ModuleSubWindow(mid, mid, QLabel("x")))
        qt_app.processEvents()
        bar = area.findChildren(
            QTabBar, options=Qt.FindChildOption.FindDirectChildrenOnly)[0]
        assert not bar.expanding()
        widths = [bar.tabRect(i).width() for i in range(bar.count())]
        assert sum(widths) < bar.width()          # 右边留空，没铺满

    def test_a_detached_view_is_not_a_top_level_window(self, qt_app):
        """摘下来的视图要**挂回窗口**当隐藏子件，不能变成独立顶层窗口。

        不挂的话：`removeSubWindow` 会让它成为一个（不可见的）顶层窗口，界面上
        悄悄攒着一堆看不见的窗口，主窗口关了它们还拖着进程。
        """
        # 放进真窗口 —— 只在"area 之上还有主窗口"时才谈得上挂回去
        # （area 自己就是顶层控件时没有可挂的地方，那时它是顶层窗口也正常）
        window = QMainWindow()
        area = WorkspaceArea()
        window.setCentralWidget(area)
        window.resize(600, 400)
        window.show()
        sub = ModuleSubWindow("a", "甲", QLabel("x"))
        area.attach(sub)
        area.detach(sub)
        assert not sub.isWindow()
        area.reattach(sub)                      # 还能回来
        assert sub in area.subWindowList()

    def test_empty_tab_bar_is_hidden(self, qt_app):
        area = WorkspaceArea()
        area.show()
        qt_app.processEvents()
        bars = area.findChildren(
            QTabBar, options=Qt.FindChildOption.FindDirectChildrenOnly)
        assert bars and not bars[0].isVisible()

    def test_maximize_on_activation_follows_the_view_mode(self, qt_app):
        """**标签页模式必须"激活即铺满"** —— 这是个不显眼但要命的开关。

        不铺满的话，Qt 会让子窗口保持各自的层叠尺寸、连标题栏一起露出来，
        界面上就是"一条标签栏 + 底下叠着几个带 ✕ 的小窗口" —— 那**根本不像
        多文件编辑器的标签**（真踩过，渲染出来才发现）。
        子窗口模式反过来：不禁掉最大化就没法并排比较。
        """
        area = WorkspaceArea()
        assert area.is_tiled_view()
        assert not area.testOption(
            QMdiArea.AreaOption.DontMaximizeSubWindowOnActivation)
        area.set_view_mode(False)
        assert area.testOption(
            QMdiArea.AreaOption.DontMaximizeSubWindowOnActivation)

    def test_active_view_fills_the_area_in_tab_mode(self, qt_app):
        """标签页模式下当前视图要**占满**整块区域（"一次只显示一个"）。"""
        area = WorkspaceArea()
        area.resize(800, 500)
        area.show()
        for mid in ("a", "b", "c"):
            area.attach(ModuleSubWindow(mid, mid, QLabel("x")))
        qt_app.processEvents()
        current = area.activeSubWindow()
        assert current is not None
        assert current.width() >= area.width() - 4
        assert current.height() >= area.height() - 40      # 顶上留一条标签栏

    def test_inner_tab_bars_of_a_view_are_untouched(self, qt_app):
        """空态藏的是**MDI 自己**那条标签栏 —— 别把视图内部的页签也藏了。"""
        from PySide6.QtWidgets import QTabWidget, QVBoxLayout
        page = QWidget()
        layout = QVBoxLayout(page)
        inner = QTabWidget(page)
        inner.addTab(QLabel("x"), "内层")
        layout.addWidget(inner)

        area = WorkspaceArea()
        area.show()
        area.attach(ModuleSubWindow("a", "甲", page))
        area.detach(ModuleSubWindow("b", "乙", QLabel("y")))     # 触发一次空态刷新
        assert inner.tabBar().isVisibleTo(inner)
