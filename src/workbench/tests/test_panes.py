"""窗格 —— 三窗格分割、空窗格塌陷、页签与标题条互斥、显隐与尺寸往返。

不依赖主窗口：`PaneLayout` 自己能建起来，这样窗格的行为可以脱离 app.py 测。
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from ..ui.panes import (DEFAULT_SIZES, NEVER_COLLAPSE, PANE_AREAS, PaneHost,
                        PaneLayout)


def _layout(qt_app) -> PaneLayout:
    layout = PaneLayout()
    # 没有窗口时 `isVisible()` 恒为 False，所以要显式 show 才能测「显示了吗」
    layout.outer.show()
    qt_app.processEvents()
    return layout


def _module(qt_app, module_id: str):
    widget = QLabel(f"module:{module_id}")
    widget.setProperty("module_id", module_id)
    return widget


class TestPaneHost:
    def test_single_tab_shows_the_header_not_the_tab_bar(self, qt_app):
        """页签栏与标题条互斥：只剩一个页签时，页签栏没意义，用标题条说明。"""
        pane = PaneHost("left")
        pane.add_module(_module(qt_app, "a.b"), "甲", "a.b")

        assert pane.header.isHidden() is False
        assert pane.tabs.tabBar().isHidden() is True

    def test_two_tabs_show_the_tab_bar_not_the_header(self, qt_app):
        pane = PaneHost("bottom")
        pane.add_module(_module(qt_app, "a.b"), "甲", "a.b")
        pane.add_module(_module(qt_app, "a.c"), "乙", "a.c")

        assert pane.tabs.tabBar().isHidden() is False
        assert pane.header.isHidden() is True

    def test_hidden_module_comes_back_at_its_old_index(self, qt_app):
        """关掉再打开要回到原位 —— 页签顺序本身是信息。"""
        pane = PaneHost("bottom")
        for name in ("甲", "乙", "丙"):
            pane.add_module(_module(qt_app, f"m.{name}"), name, f"m.{name}")

        pane.set_module_visible("m.甲", False)
        assert pane.module_ids() == ["m.乙", "m.丙"]

        pane.set_module_visible("m.甲", True)
        assert pane.module_ids() == ["m.甲", "m.乙", "m.丙"]

    def test_hidden_module_keeps_its_widget_alive(self, qt_app):
        """摘下来的是页签，不是控件 —— 模块的状态不能因为关一下就没了。"""
        pane = PaneHost("bottom")
        widget = _module(qt_app, "m.甲")
        pane.add_module(widget, "甲", "m.甲")

        pane.set_module_visible("m.甲", False)
        pane.set_module_visible("m.甲", True)
        assert pane.tabs.widget(0) is widget

    def test_pinned_tab_is_not_in_the_module_order(self, qt_app):
        """平台自带的页签（控制台、导航树）不进 `_order`，所以关不掉。"""
        pane = PaneHost("bottom")
        pane.add_pinned(_module(qt_app, "__console__"), "控制台", "__console__")
        assert pane.set_module_visible("__console__", False) is False
        assert pane.contains("__console__")

    def test_activate_switches_the_current_tab(self, qt_app):
        pane = PaneHost("bottom")
        pane.add_module(_module(qt_app, "a"), "甲", "a")
        pane.add_module(_module(qt_app, "b"), "乙", "b")

        assert pane.activate("a") is True
        assert pane.current_module_id() == "a"

    def test_activate_unknown_returns_false(self, qt_app):
        assert PaneHost("bottom").activate("nope") is False


class TestCollapse:
    def test_empty_pane_can_collapse(self, qt_app):
        layout = _layout(qt_app)
        layout.pane("left").set_collapsed(True)
        assert layout.pane("left").isHidden()

    def test_center_never_collapses(self, qt_app):
        """中心是主工作区，收起来界面就空了。"""
        layout = _layout(qt_app)
        layout.pane("center").set_collapsed(True)
        assert not layout.pane("center").isHidden()
        assert "center" in NEVER_COLLAPSE

    def test_collapse_empty_hides_only_the_empty_ones(self, qt_app):
        layout = _layout(qt_app)
        layout.pane("bottom").add_module(_module(qt_app, "a"), "甲", "a")

        layout.collapse_empty()

        assert layout.pane("left").isHidden()       # 空 → 收起
        assert layout.pane("right").isHidden()
        assert not layout.pane("bottom").isHidden()  # 有内容 → 留着
        assert not layout.pane("center").isHidden()

    def test_hiding_the_last_module_collapses_the_pane(self, qt_app):
        layout = _layout(qt_app)
        layout.pane("bottom").add_module(_module(qt_app, "a"), "甲", "a")
        layout.set_module_visible("a", False)
        assert layout.pane("bottom").isHidden()

    def test_showing_a_module_un_collapses_the_pane(self, qt_app):
        layout = _layout(qt_app)
        layout.pane("right").add_module(_module(qt_app, "a"), "甲", "a")
        layout.set_module_visible("a", False)

        assert layout.set_module_visible("a", True) is True
        assert not layout.pane("right").isHidden()
        assert layout.pane("right").contains("a")


class TestFocus:
    def test_focus_finds_the_pane_and_activates(self, qt_app):
        layout = _layout(qt_app)
        layout.pane("bottom").add_module(_module(qt_app, "a"), "甲", "a")
        layout.pane("center").add_module(_module(qt_app, "b"), "乙", "b")

        assert layout.focus("a") is True
        assert layout.pane("bottom").current_module_id() == "a"

    def test_focus_un_collapses_first(self, qt_app):
        """折叠着的窗格收到 focus 要先展开 —— 否则「切过去了但看不见」。"""
        layout = _layout(qt_app)
        layout.pane("bottom").add_module(_module(qt_app, "a"), "甲", "a")
        layout.pane("bottom").set_collapsed(True)

        assert layout.focus("a") is True
        assert not layout.pane("bottom").isHidden()

    def test_focus_unknown_module_returns_false(self, qt_app):
        assert _layout(qt_app).focus("nope") is False

    def test_pane_of_locates_the_owner(self, qt_app):
        layout = _layout(qt_app)
        layout.pane("right").add_module(_module(qt_app, "a"), "甲", "a")
        assert layout.pane_of("a") is layout.pane("right")
        assert layout.pane_of("nope") is None

    def test_unknown_area_falls_back_to_center(self, qt_app):
        """区域名认不出时宁可放错也不丢模块。"""
        layout = _layout(qt_app)
        assert layout.pane("天知道") is layout.pane("center")


class TestState:
    def test_state_round_trips(self, qt_app):
        layout = _layout(qt_app)
        layout.top.setSizes([200, 900, 300])
        layout.outer.setSizes([600, 260])
        saved = layout.state()

        other = _layout(qt_app)
        other.apply_state(saved)
        assert other.top.sizes() == layout.top.sizes()
        assert other.outer.sizes() == layout.outer.sizes()

    def test_reports_which_panes_are_visible(self, qt_app):
        layout = _layout(qt_app)
        layout.pane("right").set_collapsed(True)
        assert layout.state()["visible"]["right"] is False
        assert layout.state()["visible"]["center"] is True

    def test_garbage_state_is_ignored_not_fatal(self, qt_app):
        """布局存坏了不该让界面起不来。"""
        layout = _layout(qt_app)
        for junk in ({}, {"splitters": "不是字典"}, {"splitters": {"pane.top": [1, 2]}},
                     {"visible": {"left": "是"}}):
            layout.apply_state(junk)          # 不抛就算过

    def test_wrong_length_sizes_fall_back_to_default(self, qt_app):
        """清单里的窗格数变了（比如删掉一个区域）时，旧尺寸对不上就别硬套。"""
        layout = _layout(qt_app)
        before = layout.top.sizes()
        layout.apply_state({"splitters": {"pane.top": [1, 2]}})
        assert layout.top.sizes() == before

    def test_areas_match_the_manifest_contract(self):
        """清单里 `ModuleSpec.area` 的四个值 —— 契约不能悄悄改。"""
        assert set(PANE_AREAS) == {"center", "left", "right", "bottom"}
        assert set(DEFAULT_SIZES) == set(PANE_AREAS)


class TestRepairSavedSizes:
    """有内容的窗格不能贴回 0 宽 —— 否则表现是「加了模块但看不见」。

    来历：上次保存布局时那块窗格可能是空的，存下来就是 0。这次它装了模块却仍旧
    0 宽，用户看到的只是"新模块没出来"，猜不到要去「视图 → 重置布局」。

    **修的是存下来的那组数，不是贴完之后的几何**：窗口还没 show 时
    `QSplitter.sizes()` 给的是尚未布局的占位值，读-改-写会把刚贴回去的正确尺寸
    整个冲掉（`test_pane_sizes_round_trip` 抓到过这一幕）。所以这里测的是纯函数。
    """

    def test_a_zero_width_pane_with_content_is_repaired(self, qt_app):
        layout = _layout(qt_app)
        layout.pane("right").add_module(_module(qt_app, "x"), "x", "X")
        fixed = layout.repair_saved_sizes([300, 1000, 0], ("left", "center", "right"))
        assert fixed == [300, 1000, DEFAULT_SIZES["right"]]

    def test_an_empty_pane_keeps_its_zero(self, qt_app):
        """没有内容的窗格不该被唤醒 —— 那会在界面边上留一条空白带。"""
        layout = _layout(qt_app)
        fixed = layout.repair_saved_sizes([300, 1200, 0], ("left", "center", "right"))
        assert fixed[2] == 0

    def test_a_collapsed_pane_keeps_its_zero(self, qt_app):
        layout = _layout(qt_app)
        layout.pane("right").add_module(_module(qt_app, "x"), "x", "X")
        layout.pane("right").set_collapsed(True)
        fixed = layout.repair_saved_sizes([300, 1200, 0], ("left", "center", "right"))
        assert fixed[2] == 0

    def test_a_nonzero_size_is_left_alone(self, qt_app):
        layout = _layout(qt_app)
        layout.pane("right").add_module(_module(qt_app, "x"), "x", "X")
        assert layout.repair_saved_sizes([260, 900, 5],
                                         ("left", "center", "right")) == [260, 900, 5]

    def test_wrong_length_falls_through_to_the_existing_guard(self, qt_app):
        """长度对不上时原样返回，交给 `_apply_sizes` 的守卫去忽略整段。"""
        layout = _layout(qt_app)
        assert layout.repair_saved_sizes([1, 2], ("left", "center", "right")) == [1, 2]

    def test_the_row_above_the_bottom_pane_is_not_a_pane(self, qt_app):
        """外层分割条的第 0 项是上面那一整行，不是某块窗格 —— 用 None 跳过。"""
        layout = _layout(qt_app)
        layout.pane("bottom").add_module(_module(qt_app, "z"), "z", "Z")
        fixed = layout.repair_saved_sizes([700, 0], (None, "bottom"))
        assert fixed == [700, DEFAULT_SIZES["bottom"]]

    def test_apply_state_uses_it(self, qt_app):
        """贴回布局时这条兜底真的在路上 —— 不然上面全是空谈。"""
        layout = _layout(qt_app)
        layout.pane("right").add_module(_module(qt_app, "x"), "x", "X")
        layout.apply_state({"splitters": {"pane.top": [300, 1000, 0]}})
        assert layout.top.sizes()[2] > 0
