"""模块导航树 —— 左窗格里的那棵树。

它现在是**业务线唯一可见的地方**（菜单栏改成了 Verdi 的七项，业务线不再占
顶层菜单），所以「分组对不对」这件事比看上去重要。
"""
from __future__ import annotations

from PySide6.QtCore import Qt

from ..manifest import load_manifest_text
from ..ui import theme
from ..ui.nav_pane import GROUP_ROLE, MODULE_ROLE, NavPane
from .conftest import BROKEN_MANIFEST, STUB_MANIFEST


def _pane(qt_app, manifest):
    picked = []
    pane = NavPane(picked.append)
    pane.populate(manifest)
    return pane, picked


class TestPopulate:
    def test_top_level_items_are_the_business_lines(self, qt_app):
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, _ = _pane(qt_app, manifest)

        titles = [pane.tree.topLevelItem(i).text(0)
                  for i in range(pane.tree.topLevelItemCount())]
        assert titles == [g.title for g in manifest.sorted_groups()]

    def test_children_are_the_modules_of_that_line(self, qt_app):
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, _ = _pane(qt_app, manifest)

        debug = pane.tree.topLevelItem(0)
        titles = [debug.child(i).text(0) for i in range(debug.childCount())]
        assert titles == [m.title for m in manifest.modules_of("debug")]

    def test_covers_every_area_not_just_center(self, qt_app):
        """树里要能看到底部的模块（错误指纹那类）—— 只列 center 的话，用户
        根本不知道它存在，只能靠菜单。"""
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, _ = _pane(qt_app, manifest)

        areas = {manifest.module(mid).area for mid in pane.item_ids()}
        assert "bottom" in areas
        assert set(pane.item_ids()) == {m.id for m in manifest.enabled_modules()}

    def test_module_id_lives_in_the_item_data(self, qt_app):
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, _ = _pane(qt_app, manifest)

        item = pane.item_ids()["stub.dock_a"]
        assert item.data(0, MODULE_ROLE) == "stub.dock_a"
        assert item.data(0, GROUP_ROLE) == "debug"

    def test_empty_business_line_gets_a_placeholder(self, qt_app):
        """空业务线留一行灰字，否则看起来像树坏了。

        （注意：共用夹具的 STUB 清单里每条业务线都有模块，所以这条得自己造
        一份带空组的清单 —— 否则测的是「有模块的那条线」，什么都验不出来。）
        """
        manifest = load_manifest_text(
            "groups:\n"
            "  - {id: a, title: 有模块的线, order: 1}\n"
            "  - {id: b, title: 空线, order: 2}\n"
            "modules:\n"
            "  - {id: a.one, title: 甲, group: a, factory: m:C}",
            source="<empty-group>")
        pane, _ = _pane(qt_app, manifest)

        empty = pane.tree.topLevelItem(1)
        assert empty.text(0) == "空线"
        assert empty.childCount() == 1
        assert "还没有模块" in empty.child(0).text(0)
        assert not (empty.child(0).flags() & Qt.ItemFlag.ItemIsSelectable)

    def test_groups_are_expanded_by_default(self, qt_app):
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, _ = _pane(qt_app, manifest)
        assert pane.tree.topLevelItem(0).isExpanded()


class TestInteraction:
    def test_activate_switches_to_that_module(self, qt_app):
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, picked = _pane(qt_app, manifest)

        pane._activated(pane.item_ids()["stub.dock_a"])
        assert picked == ["stub.dock_a"]

    def test_activating_a_group_header_does_nothing(self, qt_app):
        """业务线那一行只是个分组标题，双击它不该切到任何模块。"""
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, picked = _pane(qt_app, manifest)

        pane._activated(pane.tree.topLevelItem(0))
        assert picked == []

    def test_active_module_is_the_only_bold_one(self, qt_app):
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, _ = _pane(qt_app, manifest)

        pane.set_active("stub.center")
        pane.set_active("stub.dock_a")

        bold = [mid for mid, item in pane.item_ids().items()
                if item.font(0).bold()]
        assert bold == ["stub.dock_a"]

    def test_clearing_the_active_module_unbolds_it(self, qt_app):
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, _ = _pane(qt_app, manifest)

        pane.set_active("stub.center")
        pane.set_active("")
        assert not any(item.font(0).bold() for item in pane.item_ids().values())

    def test_set_active_unknown_is_harmless(self, qt_app):
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, _ = _pane(qt_app, manifest)
        pane.set_active("根本没有这个模块")      # 不抛就算过


class TestFailures:
    def test_failed_modules_are_marked_with_the_reason(self, qt_app):
        manifest = load_manifest_text(BROKEN_MANIFEST, source="<broken>")
        pane, _ = _pane(qt_app, manifest)

        pane.set_failed({"stub.broken": "ImportError: 找不到模块"})

        item = pane.item_ids()["stub.broken"]
        assert "ImportError" in item.toolTip(0)
        assert item.foreground(0).color().name() == theme.SEVERITY["error"].name()

    def test_healthy_modules_stay_unmarked(self, qt_app):
        manifest = load_manifest_text(BROKEN_MANIFEST, source="<broken>")
        pane, _ = _pane(qt_app, manifest)

        pane.set_failed({"stub.broken": "boom"})

        healthy = pane.item_ids()["stub.center"]
        assert "boom" not in healthy.toolTip(0)

    def test_unknown_failure_id_is_ignored(self, qt_app):
        manifest = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, _ = _pane(qt_app, manifest)
        pane.set_failed({"从来没有过的模块": "boom"})   # 不抛就算过


class TestRebuild:
    def test_repopulating_clears_the_previous_tree(self, qt_app):
        first = load_manifest_text(STUB_MANIFEST, source="<stub>")
        pane, _ = _pane(qt_app, first)
        pane.set_active("stub.center")

        second = load_manifest_text(BROKEN_MANIFEST, source="<broken>")
        pane.populate(second)

        assert "stub.broken" in pane.item_ids()
        assert pane.tree.topLevelItem(0).isExpanded()
        assert not any(item.font(0).bold() for item in pane.item_ids().values())
