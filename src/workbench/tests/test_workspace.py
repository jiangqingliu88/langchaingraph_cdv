"""工作区 —— MDI 子窗口 + Dock 侧栏。

**这是 `test_panes.py` 的替代品。** 外壳从「固定四窗格 QSplitter」换成了
「QMdiArea 中央 + QDockWidget 侧栏」（见 `ui/workspace.py`），原来那份测的是
窗格/页签，现在测子窗口/dock —— 测的东西换了，但**要保的语义没换**：

  · 模块按 `area` 落位（center→子窗口，其余→dock）
  · 显隐可切换，**控件活着**（模块状态不因关一下就丢）
  · `focus` 找得到、抬得起
  · 平台自带的（导航树 / 控制台）关不掉
  · 布局存得下、贴得回，存坏了不炸

`Workspace` 自己能建起来（只要给个 QMainWindow），这样它的行为可以脱离 app.py 测。
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import (QDockWidget, QLabel, QMainWindow, QTabBar,
                               QTabWidget, QVBoxLayout, QWidget)

from PySide6.QtCore import Qt

from ..ui.containers.workspace import DOCK_AREAS, PANE_AREAS, Workspace


def _workspace(qt_app) -> Workspace:
    window = QMainWindow()
    ws = Workspace(window, close_guard=lambda _mid: True)
    # 挂成 central widget —— 与 app.py 一致。不挂的话 MDI 不在窗口层级里，
    # 里面控件的 `isVisible()` 恒为 False（那测的是"没显示"，不是"被藏了"）。
    window.setCentralWidget(ws.mdi)
    window.show()
    qt_app.processEvents()
    return ws


def _module(module_id: str) -> QLabel:
    widget = QLabel(f"module:{module_id}")
    widget.setProperty("module_id", module_id)
    return widget


class TestAreas:
    def test_area_contract_is_unchanged(self):
        """清单里 `ModuleSpec.area` 的四个值 —— 契约没变，变的只是渲染方式。"""
        assert set(PANE_AREAS) == {"center", "left", "right", "bottom"}
        assert set(DOCK_AREAS) == {"left", "right", "bottom"}

    def test_center_module_becomes_a_subwindow(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        assert ws.subwindow_count("a") == 1
        assert ws.dock_of("a") is None

    def test_side_module_becomes_a_dock(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "left")
        assert ws.dock_of("a") is not None
        assert ws.subwindow_count("a") == 0

    def test_pane_of_reports_the_area(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("c"), "中", "c", "center")
        ws.add_module(_module("r"), "右", "r", "right")
        assert ws.pane_of("c") == "center"
        assert ws.pane_of("r") == "right"
        assert ws.pane_of("nope") is None

    def test_modules_in_lists_by_area(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "bottom")
        ws.add_module(_module("b"), "乙", "b", "bottom")
        ws.add_module(_module("c"), "丙", "c", "center")
        assert ws.modules_in("bottom") == ["a", "b"]
        assert ws.modules_in("center") == ["c"]


class TestDockTabify:
    """同区 dock 要**叠成页签**（底部一条可点的标签条），不要并排分割。

    不 tabify 的话 Qt 会把同区 dock 拆开排列 —— 左边两块各占一半、谁也看不清，
    而且没有"切换按钮"这回事。
    """

    def test_same_area_docks_are_tabified(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "left")
        ws.add_module(_module("b"), "乙", "b", "left")
        assert ws.window.tabifiedDockWidgets(ws.dock_of("a")) == [ws.dock_of("b")]

    def test_different_areas_are_not_tabified(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "left")
        ws.add_module(_module("b"), "乙", "b", "right")
        assert ws.window.tabifiedDockWidgets(ws.dock_of("a")) == []

    def test_the_first_dock_stays_in_front(self, qt_app):
        """左边默认该看见导航树（先加的），不是后加的模块把它盖住。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("__nav__"), "模块", "__nav__", "left")
        ws.add_module(_module("runs"), "运行历史", "runs", "left")
        assert ws.dock_of("__nav__").isVisible()

    def test_reopening_a_tabified_dock_raises_it(self, qt_app):
        """从菜单打开一个叠着的 dock，必须抬到前面 —— 否则"打开了但看不见"。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("__nav__"), "模块", "__nav__", "left")
        ws.add_module(_module("runs"), "运行历史", "runs", "left")
        ws.set_module_visible("runs", False)
        ws.set_pinned_visible("runs", True)
        assert ws.contains("runs")

    def test_docks_stay_draggable_and_floatable(self, qt_app):
        """叠成页签不牺牲 Dock 的本分：还能拖到别的边、也能拖出来浮动。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "left")
        features = ws.dock_of("a").features()
        assert features & QDockWidget.DockWidgetFeature.DockWidgetMovable
        assert features & QDockWidget.DockWidgetFeature.DockWidgetFloatable


class TestMultiOpen:
    """center 模块可多开 —— 这是 MDI 相对页签的核心区别。"""

    def test_a_module_can_have_several_subwindows(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.add_module(_module("a"), "甲", "a", "center")
        assert ws.subwindow_count("a") == 2
        assert ws.subwindow_count() == 2

    def test_each_instance_keeps_its_own_widget(self, qt_app):
        ws = _workspace(qt_app)
        one, two = _module("a"), _module("a")
        ws.add_module(one, "甲", "a", "center")
        ws.add_module(two, "甲", "a", "center")
        widgets = [s.widget() for s in ws.subwindows_of("a")]
        assert widgets[0] is one and widgets[1] is two

    def test_focus_raises_the_newest_instance(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.focus("a")
        assert ws.active_module_id() == "a"
        assert ws.mdi.activeSubWindow() is ws.subwindows_of("a")[-1]

    def test_ordered_module_ids_follow_creation_order(self, qt_app):
        """`subWindowList()` 默认是**层叠**顺序，会随用户点哪一下而变 ——
        要清单顺序必须显式要 CreationOrder。"""
        ws = _workspace(qt_app)
        for mid in ("a", "b", "c"):
            ws.add_module(_module(mid), mid, mid, "center")
        ws.focus("a")                     # 把第一个抬到最前
        assert ws.ordered_module_ids() == ["a", "b", "c"]

    def test_docks_stay_single(self, qt_app):
        """dock 位只有一个，"开两个"没有承载它的地方。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "left")
        ws.add_module(_module("a"), "甲", "a", "left")
        assert ws.dock_of("a") is ws.dock_of("a")


class TestVisibility:
    def test_hidden_module_keeps_its_widget_alive(self, qt_app):
        """关掉的是窗口，不是控件 —— 模块的状态不能因为关一下就没了。"""
        ws = _workspace(qt_app)
        widget = _module("a")
        ws.add_module(widget, "甲", "a", "center")
        ws.set_module_visible("a", False)
        ws.set_module_visible("a", True)
        assert ws.subwindows_of("a")[0].widget() is widget

    def test_contains_reflects_visibility(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        assert ws.contains("a")
        ws.set_module_visible("a", False)
        assert not ws.contains("a")
        assert ws.set_module_visible("a", True) is True
        assert ws.contains("a")

    def test_contains_does_not_trust_isvisible(self, qt_app):
        """**别信 `isVisible()`** —— 窗口没 show 过时它恒为 False，那会把
        「还没显示」误判成「已隐藏」。这里特意不 show 任何东西。"""
        window = QMainWindow()
        ws = Workspace(window, close_guard=lambda _m: True)
        ws.add_module(_module("a"), "甲", "a", "center")
        assert ws.contains("a")
        assert "a" in ws.module_ids()

    def test_pinned_dock_cannot_be_hidden(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_pinned(_module("__console__"), "控制台", "__console__", "bottom")
        assert ws.set_module_visible("__console__", False) is False
        assert ws.contains("__console__")

    def test_pinned_dock_can_be_toggled_by_the_platform(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_pinned(_module("__nav__"), "模块", "__nav__", "left")
        assert ws.set_pinned_visible("__nav__", False) is True
        assert not ws.contains("__nav__")
        assert ws.set_pinned_visible("__nav__", True) is True

    def test_hiding_unknown_is_harmless(self, qt_app):
        assert _workspace(qt_app).set_module_visible("nope", False) is False


class TestFocus:
    def test_focus_unknown_returns_false(self, qt_app):
        assert _workspace(qt_app).focus("nope") is False

    def test_focus_reopens_a_hidden_subwindow(self, qt_app):
        """关掉之后从菜单/导航树再点它 —— 要能回来。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.set_module_visible("a", False)
        assert ws.focus("a") is True
        assert ws.contains("a")

    def test_focus_raises_a_hidden_dock(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "right")
        ws.set_module_visible("a", False)
        assert ws.focus("a") is True
        assert ws.contains("a")

    def test_active_module_id_is_empty_when_nothing_focused(self, qt_app):
        ws = _workspace(qt_app)
        assert ws.active_module_id() == ""


class TestSuffix:
    def test_suffix_is_recomputed_from_the_base_title(self, qt_app):
        """后缀从**原名**重拼 —— 直接往当前标题上接会越叠越长。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.set_suffix("a", " ●")
        ws.set_suffix("a", " ●")
        assert ws.subwindows_of("a")[0].windowTitle() == "甲 ●"

    def test_suffix_reaches_docks_too(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "left")
        ws.set_suffix("a", " ●")
        assert ws.dock_of("a").windowTitle() == "甲 ●"

    def test_suffix_reaches_every_instance(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.set_suffix("a", " ●")
        assert all(s.windowTitle() == "甲 ●" for s in ws.subwindows_of("a"))

    def test_suffix_on_unknown_is_harmless(self, qt_app):
        _workspace(qt_app).set_suffix("nope", " ●")


class TestLayout:
    def test_save_layout_returns_docks_and_a_json_snapshot(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        docks, subs = ws.save_layout()
        assert docks is not None and bytes(docks)          # QByteArray 有内容
        saved = json.loads(subs)
        assert saved["view"] == "tabs"                     # 视图模式也在快照里
        assert [item["module"] for item in saved["subwindows"]] == ["a"]

    def test_subwindow_geometry_round_trips(self, qt_app):
        first = _workspace(qt_app)
        first.add_module(_module("a"), "甲", "a", "center")
        first.subwindows_of("a")[0].setGeometry(70, 80, 510, 420)
        docks, subs = first.save_layout()

        second = _workspace(qt_app)
        second.add_module(_module("a"), "甲", "a", "center")
        second.restore_layout(docks, subs)
        geo = second.subwindows_of("a")[0].geometry()
        assert (geo.x(), geo.y(), geo.width(), geo.height()) == (70, 80, 510, 420)

    def test_garbage_layout_is_ignored_not_fatal(self, qt_app):
        """布局存坏了不该让界面起不来。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        for junk in ("", "{这不是 json", "[]", '"字符串"', None, 42):
            ws.restore_layout(None, junk)          # 不抛就算过
        ws.restore_layout(b"\x00\xff\x13\x37", "")   # dock 那半也试一遍（随便一串字节）
        assert ws.contains("a")

    def test_hidden_state_round_trips(self, qt_app):
        first = _workspace(qt_app)
        first.add_module(_module("a"), "甲", "a", "center")
        first.set_module_visible("a", False)
        docks, subs = first.save_layout()

        second = _workspace(qt_app)
        second.add_module(_module("a"), "甲", "a", "center")
        second.restore_layout(docks, subs)
        assert not second.contains("a")


class TestLazyGeometry:
    """center 模块是点了才开的 —— 贴布局时它还不存在，几何得**等它被打开时**再套。"""

    def test_geometry_stored_before_opening_is_applied_on_open(self, qt_app):
        ws = _workspace(qt_app)
        ws.restore_layout(None, json.dumps(
            {"view": "windows",
             "subwindows": [{"module": "later", "x": 30, "y": 40,
                             "w": 410, "h": 320, "open": True}]}))
        ws.add_module(_module("later"), "迟到的", "later", "center")
        geo = ws.subwindows_of("later")[0].geometry()
        assert (geo.x(), geo.y(), geo.width(), geo.height()) == (30, 40, 410, 320)


class TestTabChrome:
    """标签栏该有的东西：**× 关闭**，以及**拖不动**。

    拖不动是有意的：TabbedView 下拖拽会把标签拽成一个浮在工作区里的子窗口 ——
    那正是"页面自己独立出来"。要独立窗口的人走 dock 那套（dock 是可浮动的）。
    """

    def test_tabs_are_closable(self, qt_app):
        assert _workspace(qt_app).mdi.tabsClosable()

    def test_every_tab_has_a_close_button(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.add_module(_module("b"), "乙", "b", "center")
        bar = ws.mdi.findChildren(
            QTabBar, options=Qt.FindChildOption.FindDirectChildrenOnly)[0]
        assert bar.count() == 2
        for index in range(bar.count()):
            assert bar.tabButton(index, QTabBar.ButtonPosition.RightSide) is not None

    def test_tabs_cannot_be_dragged_out(self, qt_app):
        assert not _workspace(qt_app).mdi.tabsMovable()


class TestEmptyState:
    """空工作区不是"一片空白" —— 给一句引导，并把那条空标签栏藏掉。"""

    @staticmethod
    def _mdi_bar(ws):
        return ws.mdi.findChildren(
            QTabBar, options=Qt.FindChildOption.FindDirectChildrenOnly)[0]

    def test_empty_workspace_shows_the_hint_and_hides_the_tab_bar(self, qt_app):
        ws = _workspace(qt_app)
        assert ws.mdi.empty_hint.isVisible()                       
        assert not self._mdi_bar(ws).isVisible()

    def test_opening_hides_the_hint_and_shows_the_tab_bar(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        assert not ws.mdi.empty_hint.isVisible()                   
        assert self._mdi_bar(ws).isVisible()

    def test_closing_a_tab_removes_it_and_brings_the_hint_back(self, qt_app):
        """标签页模式下 `setVisible(False)` **不摘标签** —— 必须走
        `removeSubWindow`，否则看着像"关不掉"。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.add_module(_module("b"), "乙", "b", "center")
        assert ws.set_module_visible("a", False) is True
        titles = [s.windowTitle() for s in ws.mdi.subWindowList()]
        assert titles == ["乙"]

        ws.set_module_visible("b", False)
        assert ws.mdi.subWindowList() == []
        assert ws.mdi.empty_hint.isVisible()                       

    def test_reopening_a_closed_tab_brings_it_back(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.set_module_visible("a", False)
        assert ws.focus("a") is True
        assert [s.windowTitle() for s in ws.mdi.subWindowList()] == ["甲"]

    def test_module_inner_tab_bars_are_not_touched(self, qt_app):
        """**别把模块内部的标签栏当成 MDI 的** —— `findChildren` 默认递归，
        会把 case 建模那 11 页、运行清单的内层页签一起捞进来藏掉。"""
        from PySide6.QtWidgets import QTabWidget
        ws = _workspace(qt_app)
        page = QWidget()
        inner = QVBoxLayout(page)
        tabs = QTabWidget(page)
        tabs.addTab(QLabel("x"), "内层页签")
        inner.addWidget(tabs)
        ws.add_module(page, "带内层页签的", "inner", "center")
        ws.set_module_visible("inner", False)          # 回到空态（会去藏 MDI 标签栏）
        # 模块**自己的**页签栏不受影响 —— 它仍然在自己的父控件里可见
        assert tabs.tabBar().isVisibleTo(tabs)


class TestMdiArrange:
    def test_default_is_tabbed_view_like_vscode(self, qt_app):
        """**默认 = 标签页模式** —— 一次开多个、顶部一条标签栏点着切。

        子窗口模式（可并排/可浮动）仍然在，只是改成视图菜单里按需切。
        """
        assert _workspace(qt_app).is_tiled_view()

    def test_view_mode_round_trips(self, qt_app):
        ws = _workspace(qt_app)
        ws.set_view_mode(False)
        assert not ws.is_tiled_view()
        ws.set_view_mode(True)
        assert ws.is_tiled_view()

    def test_switching_between_instances_in_tab_mode(self, qt_app):
        """切成标签页模式后，多开的两个窗口是两条标签 —— 点标签切。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.set_view_mode(True)
        assert ws.is_tiled_view()
        ws.focus("a")
        qt_app.processEvents()
        assert ws.active_module_id() == "a"
        assert ws.mdi.activeSubWindow() is ws.subwindows_of("a")[-1]

    def test_tile_switches_back_to_subwindow_view(self, qt_app):
        """标签页里"平铺"没有意义 —— 点它要先切回子窗口模式，
        否则点了什么都不发生，用户以为按钮坏了。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.set_view_mode(True)
        assert ws.is_tiled_view()
        ws.tile()
        assert not ws.is_tiled_view()

    def test_cascade_switches_back_to_subwindow_view(self, qt_app):
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.cascade()
        assert not ws.is_tiled_view()

    def test_tile_and_cascade_do_not_blow_up(self, qt_app):
        ws = _workspace(qt_app)
        for mid in ("a", "b"):
            ws.add_module(_module(mid), mid, mid, "center")
        ws.tile()
        ws.cascade()
        ws.activate_next()

    def test_view_mode_round_trips_through_the_layout_snapshot(self, qt_app):
        first = _workspace(qt_app)
        first.add_module(_module("a"), "甲", "a", "center")
        first.set_view_mode(False)                     # 用户切成了独立窗口
        docks, subs = first.save_layout()

        second = _workspace(qt_app)
        second.add_module(_module("a"), "甲", "a", "center")
        second.restore_layout(docks, subs)
        assert not second.is_tiled_view()              # 他的选择被记住

    def test_old_list_format_snapshot_still_loads(self, qt_app):
        """更早存过一份**纯列表**的子窗口快照 —— 读回来也要认，
        否则用户升一次级布局就没了。"""
        ws = _workspace(qt_app)
        ws.add_module(_module("a"), "甲", "a", "center")
        ws.restore_layout(None, json.dumps(
            [{"module": "a", "x": 11, "y": 12, "w": 300, "h": 200, "open": True}]))
        geo = ws.subwindows_of("a")[0].geometry()
        assert (geo.x(), geo.y(), geo.width(), geo.height()) == (11, 12, 300, 200)
        assert ws.is_tiled_view()                      # 旧格式没带视图模式 → 用默认


class TestCloseGuard:
    def test_guard_can_refuse_a_close(self, qt_app):
        """模块说有未保存改动时，子窗口不该被关掉。"""
        window = QMainWindow()
        ws = Workspace(window, close_guard=lambda _mid: False)
        window.show()
        ws.add_module(_module("a"), "甲", "a", "center")
        sub = ws.subwindows_of("a")[0]
        sub.close()
        assert not sub.isHidden()          # 被守卫拦下了

    def test_guard_lets_a_clean_module_close(self, qt_app):
        window = QMainWindow()
        ws = Workspace(window, close_guard=lambda _mid: True)
        window.show()
        ws.add_module(_module("a"), "甲", "a", "center")
        sub = ws.subwindows_of("a")[0]
        sub.close()
        assert sub.isHidden()
