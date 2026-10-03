"""菜单结构 —— Verdi 形的七个菜单。

菜单栏的形状是「像不像 Verdi」最容易看出的一处：Verdi 是
File/View/Trace/Tools/Window/Help 那一套，不是「每条业务线一个顶层菜单」。
"""
from __future__ import annotations

from ..manifest import load_manifest_text
from .conftest import (BROKEN_MANIFEST, STUB_MANIFEST, entries, make_window,
                       menu_by_title, menu_titles)

EXPECTED = ["文件", "编辑", "视图", "调试", "工具", "窗口", "帮助"]


class TestTopLevel:
    def test_seven_menus_in_order(self, window):
        assert menu_titles(window) == EXPECTED

    def test_business_lines_are_not_top_level(self, window):
        """业务线不占顶层菜单 —— 否则每加一条线菜单栏就长一节。

        它们落在**窗口**菜单里（下面按业务线分段）与左窗格的导航树上。
        """
        titles = menu_titles(window)
        assert "调试技术" not in titles
        assert "验证管理系统" not in titles

    def test_menus_stay_alive(self, window):
        """每个菜单都得有人持有引用。

        `QMenuBar.addMenu(字符串)` 返回的 QMenu 若没人持有，PySide 会连 C++
        对象一起回收 —— 菜单栏上还画着，拿到手却是
        `Internal C++ object (QMenu) already deleted`。踩过，所以钉住。
        """
        for title in window._menus:                       # noqa: SLF001
            assert window.menu(title).actions() is not None


class TestWindowMenu:
    def test_lists_every_module_flat(self, window):
        """模块平铺在窗口菜单下（不做嵌套子菜单），业务线用小标题行分组。"""
        texts = [a.text() for a in menu_by_title(window, "窗口").actions()]
        assert any("中央页" in t for t in texts)
        assert any("底部甲" in t for t in texts)
        assert any("第二个中央页" in t for t in texts)

    def test_group_titles_are_disabled_headers(self, window):
        menu = menu_by_title(window, "窗口")
        headers = [a for a in menu.actions()
                   if a.text() in ("调试技术", "验证管理系统")]
        assert headers, "窗口菜单里没有业务线小标题"
        for header in headers:
            assert not header.isEnabled(), "小标题只是分组标签，不该能点"

    def test_center_modules_are_open_entries(self, window):
        entry = next(a for a in menu_by_title(window, "窗口").actions()
                     if "中央页" in a.text())
        assert entry.text() == "打开「中央页」"
        assert not entry.isCheckable()

    def test_dock_modules_are_checkable_toggles(self, window):
        """非中央的模块是可勾选的显隐开关 —— 关掉一个页签之后总得有地方再打开。"""
        entry = next(a for a in menu_by_title(window, "窗口").actions()
                     if "底部甲" in a.text())
        assert entry.isCheckable()
        assert entry.isChecked()

    def test_toggling_from_the_menu_hides_and_shows_the_module(self, window):
        entry = next(a for a in menu_by_title(window, "窗口").actions()
                     if "底部甲" in a.text())
        entry.setChecked(False)
        assert not window.manager.pane_of("stub.dock_a").contains("stub.dock_a")

        entry.setChecked(True)
        assert window.manager.pane_of("stub.dock_a").contains("stub.dock_a")

    def test_failed_modules_are_disabled_in_the_window_menu(self, qt_app, ctx):
        ctx.manifest = load_manifest_text(BROKEN_MANIFEST, source="<broken>")
        window = make_window(qt_app, ctx)
        try:
            entry = next(a for a in menu_by_title(window, "窗口").actions()
                         if "坏的底部" in a.text())
            assert "加载失败" in entry.text()
            assert not entry.isEnabled()
        finally:
            window.manager.mark_all_clean()
            window.close()


class TestActionMenus:
    def test_module_actions_land_in_the_tools_menu(self, window):
        """业务线不叫 debug 的模块，动作进「工具」。"""
        texts = [a.text() for a in menu_by_title(window, "工具").actions()]
        assert "假动作" in texts
        assert "第二个中央页" in texts          # 模块标题当分隔行

    def test_debug_group_would_go_to_the_debug_menu(self, qt_app, ctx):
        """debug 业务线的动作进「调试」—— Verdi 的 Trace 菜单就是这个位置。"""
        ctx.manifest = load_manifest_text(
            "groups: [{id: debug, title: 调试技术}]\n"
            "modules:\n"
            "  - {id: d.one, title: 甲, group: debug, factory: "
            "\"src.workbench.tests.stub_modules:StubModuleWithAction\"}",
            source="<debug-group>")
        window = make_window(qt_app, ctx)
        try:
            assert [a.text() for a in menu_by_title(window, "调试").actions()] == \
                ["甲", "假动作"]
            assert menu_by_title(window, "工具").actions() == []
        finally:
            window.manager.mark_all_clean()
            window.close()


class TestViewMenu:
    def test_has_the_pane_toggles(self, window):
        texts = [a.text() for a in menu_by_title(window, "视图").actions()]
        assert "模块导航树" in texts
        assert "控制台" in texts
        assert "重置布局" in texts

    def test_has_one_entry_per_theme(self, window):
        from ..ui import theme
        texts = [a.text() for a in menu_by_title(window, "视图").actions()]
        for name in theme.PALETTES:
            assert name in texts

    def test_hiding_the_nav_collapses_the_left_pane(self, window):
        """导航树是左窗格唯一的常驻页签 —— 收起它，左窗格就该消失。"""
        assert not window.panes.pane("left").is_collapsed()
        window.act_toggle_nav.setChecked(False)
        assert window.panes.pane("left").is_collapsed()

        window.act_toggle_nav.setChecked(True)
        assert not window.panes.pane("left").is_collapsed()

    def test_hiding_the_console_keeps_the_bottom_pane_for_modules(self, window):
        """底窗格还有模块页签，控制台关掉不该把整块窗格也收走。"""
        window.act_toggle_console.setChecked(False)
        assert not window.panes.pane("bottom").contains("__console__")
        assert not window.panes.pane("bottom").is_collapsed()


class TestFileAndHelp:
    def test_file_menu_has_manifest_actions(self, window):
        texts = [a.text() for a in menu_by_title(window, "文件").actions()]
        assert "载入清单…" in texts
        assert "重新载入清单" in texts
        assert "退出" in texts

    def test_edit_menu_forwards_to_the_focused_widget(self, window):
        texts = [a.text() for a in menu_by_title(window, "编辑").actions()]
        assert "复制" in texts and "全选" in texts and "清空控制台" in texts

    def test_clear_console_empties_it(self, window):
        window.console.append("一行日志", "info")
        assert window.console.lines()
        window.act_clear_console.trigger()
        assert window.console.lines() == []

    def test_help_menu_has_about(self, window):
        texts = [a.text() for a in menu_by_title(window, "帮助").actions()]
        assert any("关于" in t for t in texts)


class TestNoDeadEntries:
    def test_entries_helper_sees_nested_menus(self, window):
        """`entries` 会递归进子菜单 —— 现在没有子菜单，但要保证它对
        平铺结构也给全量。"""
        flat = [a.text() for a in menu_by_title(window, "窗口").actions()]
        assert [a.text() for a in entries(menu_by_title(window, "窗口"))] == flat
