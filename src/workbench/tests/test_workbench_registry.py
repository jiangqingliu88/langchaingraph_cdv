"""模块管理器 —— 清单怎么落成标签页 / Dock / 菜单。

用 `stub_modules` 里的假模块：清单到界面的这条路不该依赖真模块能不能 import。
"""
from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit

from ..manifest import load_manifest_text
from .conftest import (BROKEN_MANIFEST, DIRTY_MANIFEST, STUB_MANIFEST,
                       SUBSCRIBER_MANIFEST, make_window, window_menu_entry)


class TestBuild:
    def test_center_tabs_follow_group_order_then_module_order(self, window):
        """桩清单里 vms 那页的模块 order 更小，但 debug 业务线排在前面。"""
        titles = [window.center_tabs.tabText(i)
                  for i in range(window.center_tabs.count())]
        assert titles == ["中央页", "第二个中央页"]

    def test_same_area_modules_share_one_pane(self, window):
        """同区的模块是**同一块窗格**里的页签 —— 一个窗格本身就是 QTabWidget，
        所以不再需要以前那种「把两个 dock tabify 起来」的动作。"""
        pane = window.manager.pane_of("stub.dock_a")
        assert pane is not None
        assert pane is window.manager.pane_of("stub.dock_b")
        assert pane.area == "bottom"
        assert {"stub.dock_a", "stub.dock_b"} <= set(pane.module_ids())

    def test_tab_widget_carries_the_module_id(self, window):
        """页签控件身上带着 module_id —— 平台靠它认人（标题、聚焦、显隐）。"""
        pane = window.manager.pane_of("stub.dock_b")
        index = pane.index_of("stub.dock_b")
        assert pane.tabs.widget(index).property("module_id") == "stub.dock_b"

    def test_every_module_is_reachable_by_id(self, window):
        assert window.manager.module("stub.center").title == "中央页"
        assert window.manager.module("nope") is None
        assert {m.module_id for m in window.modules} == {
            "stub.center", "stub.center2", "stub.dock_a", "stub.dock_b"}

    def test_group_filtering_on_modules(self, window):
        assert {m.module_id for m in window.manager.modules("debug")} == {
            "stub.center", "stub.dock_a", "stub.dock_b"}
        assert window.manager.modules("nope") == []

    def test_module_actions_reach_the_toolbar(self, window, qt_app):
        toolbar_texts = [a.text() for a in window.toolbar.actions()]
        assert "假动作" in toolbar_texts


class TestFocus:
    def test_focus_switches_the_center_tab(self, window):
        assert window.manager.focus("stub.center2")
        assert window.center_tabs.tabText(window.center_tabs.currentIndex()) == "第二个中央页"

    def test_focus_switches_the_tab_inside_the_pane(self, window):
        """不光要返回 True —— 得真的切过去。只断言返回值的话，实现改成
        「找到了但没切」也照样通过。"""
        assert window.manager.focus("stub.dock_a")
        assert window.manager.pane_of("stub.dock_a").current_module_id() == "stub.dock_a"

    def test_focus_unknown_module_returns_false(self, window):
        assert not window.manager.focus("nope")


class TestFailureIsolation:
    """"一个模块坏了不拖垮界面" —— 这条是从旧界面沿用的核心原则。"""

    @staticmethod
    def _broken(qt_app, ctx):
        ctx.manifest = load_manifest_text(BROKEN_MANIFEST, source="<broken>")
        return make_window(qt_app, ctx)

    def test_broken_module_is_recorded_not_raised(self, qt_app, ctx):
        window = self._broken(qt_app, ctx)
        try:
            assert set(window.manager.failures()) == {"stub.broken", "stub.broken_dock"}
            assert window.manager.module("stub.broken") is None
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_other_modules_still_build(self, qt_app, ctx):
        window = self._broken(qt_app, ctx)
        try:
            titles = [window.center_tabs.tabText(i)
                      for i in range(window.center_tabs.count())]
            assert "中央页" in titles
            assert "坏模块" in titles          # 占位页仍然出现，让人看见它坏了
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_the_broken_tab_shows_the_traceback(self, qt_app, ctx):
        window = self._broken(qt_app, ctx)
        try:
            index = next(i for i in range(window.center_tabs.count())
                         if window.center_tabs.tabText(i) == "坏模块")
            widget = window.center_tabs.widget(index)
            assert isinstance(widget, QPlainTextEdit)
            assert "NoSuchModuleAnywhere" in widget.toPlainText()
            assert "其余模块不受影响" in widget.toPlainText()
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_window_banner_reports_the_failure(self, qt_app, ctx):
        window = self._broken(qt_app, ctx)
        try:
            assert window.banner.is_showing
            assert window.banner.kind == "error"
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_failed_module_still_shows_but_its_toggle_is_disabled(self, qt_app, ctx):
        """坏掉的模块仍然占着一个页签（让人看见它坏了），但菜单项是灰的 ——
        别让人以为点一下就能修好。"""
        window = self._broken(qt_app, ctx)
        try:
            pane = window.manager.pane_of("stub.broken_dock")
            assert pane is not None and pane.contains("stub.broken_dock")
            entry = window_menu_entry(window, "坏的底部")
            assert "加载失败" in entry.text()
            assert not entry.isEnabled()
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_failed_center_module_is_not_offered_for_switching(self, qt_app, ctx):
        """中央的坏模块在窗口菜单里同样是灰的。"""
        window = self._broken(qt_app, ctx)
        try:
            entry = window_menu_entry(window, "坏模块")
            assert not entry.isEnabled()
        finally:
            window.manager.mark_all_clean()
            window.close()


class TestCloseGate:
    def test_all_clean_modules_allow_closing(self, window):
        assert window.manager.close_all()

    def test_a_dirty_module_blocks_closing_until_cleaned(self, qt_app, ctx):
        ctx.manifest = load_manifest_text(DIRTY_MANIFEST, source="<dirty>")
        window = make_window(qt_app, ctx)
        try:
            assert not window.manager.close_all()
            window.manager.mark_all_clean()
            assert window.manager.close_all()
        finally:
            window.manager.mark_all_clean()
            window.close()


class TestWindowSize:
    """窗口不该比屏幕还大 —— 那表现成「界面被切掉一块」，看着像 bug。"""

    def test_size_is_clamped_to_the_available_screen(self, qt_app, ctx):
        ctx.manifest = load_manifest_text(
            "window: {size: [99999, 99999], min_size: [99999, 99999]}\n"
            "groups: [{id: a, title: A}]\nmodules: []", source="<huge>")
        window = make_window(qt_app, ctx)
        try:
            available = qt_app.primaryScreen().availableGeometry()
            assert window.width() <= available.width()
            assert window.height() <= available.height()
            # 最小尺寸也得跟着夹，否则窗口被强制撑到屏幕外，夹了等于没夹
            assert window.minimumWidth() <= window.width()
            assert window.minimumHeight() <= window.height()
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_size_never_exceeds_what_the_manifest_asks_for(self, window, manifest):
        """清单要多大就多大 —— 只是屏幕装不下时会缩。

        不断言「正好等于清单值」：offscreen 平台的虚拟屏幕只有 800x600，
        夹取本身就在正常工作，那正是这条规则存在的意义。
        """
        width, height = manifest.window.size
        assert 640 <= window.width() <= width
        assert 480 <= window.height() <= height


class TestLayoutPersistence:
    """关窗口存的几何与 Dock 布局，下次开要能贴回来。

    这条路径此前只有「关了窗口确实写了设置」的间接证据，没有往返验证 ——
    而它正是 `setObjectName`/`saveState` 那一串约定存在的唯一理由。
    """

    #: 默认桩清单是 restore_layout: false（免得每个测试都去碰 QSettings），
    #: 这个类要的正是「会恢复」的那份。
    RESTORING = STUB_MANIFEST.replace("restore_layout: false",
                                      "restore_layout: true")

    #: 尺寸小、且**最小尺寸明显小于默认尺寸**的一份。
    #: 默认桩清单的 min_size 是 1080x680，在 offscreen 的 800x800 虚拟屏上会被
    #: 夹到和默认尺寸一样大 —— 那时窗口根本缩不小，也就没有「比默认更小的几何
    #: 能否恢复」可测。
    SMALL = """
version: 1
window:
  title: 测试工作台
  size: [600, 500]
  min_size: [320, 240]
  restore_layout: true
groups:
  - {id: debug, title: 调试技术, order: 10}
modules: []
"""

    def _manifest(self):
        return load_manifest_text(self.RESTORING, source="<restoring>")

    def test_position_round_trips(self, qt_app, ctx):
        """位置与尺寸要能贴回来。

        用一个**装得下**的几何：Qt 的 `restoreGeometry` 会把存下来的几何裁进
        当前屏幕，offscreen 的虚拟屏只有 800x800，拿 1234x777 去测，收到的
        是被 Qt 裁过的 798x774 —— 那验证的是 Qt 的适配逻辑，不是我们的存取。
        """
        from PySide6.QtCore import QPoint, QSize

        ctx.manifest = load_manifest_text(self.SMALL, source="<small>")
        first = make_window(qt_app, ctx)
        first.resize(500, 400)               # 比默认 600x500 小，但高于最小 320x240
        first.move(30, 40)
        first.ctx.settings.save_window(first, theme="探针", center_tab=0)
        first.manager.mark_all_clean()
        first.close()

        second = make_window(qt_app, ctx)
        try:
            assert second.size() == QSize(500, 400)
            assert second.pos() == QPoint(30, 40)
        finally:
            second.manager.mark_all_clean()
            second.close()

    def test_pane_sizes_round_trip(self, qt_app, ctx):
        """窗格尺寸存得下、贴得回。

        （Dock 时代这条测的是 `saveState` 那个二进制块；改三窗格之后
        `saveState` 什么也不认了，所以换成尺寸数组的往返。）
        """
        ctx.manifest = self._manifest()
        first = make_window(qt_app, ctx)
        # 必须 show 过才谈得上尺寸：没显示的 splitter 还没算过布局，
        # `setSizes` 给的数会被下一次布局改写。
        first.show()
        qt_app.processEvents()
        first.panes.outer.setSizes([500, 300])
        qt_app.processEvents()
        # 记**归一化之后**的尺寸：Qt 会按各页的最小尺寸把请求值调一调，
        # 断言「等于我设的值」会跟 Qt 的约束较劲，断言「贴回来的和当初看着
        # 一样」才是真正要保的东西。
        want = first.panes.outer.sizes()
        first.ctx.settings.save_window(first, theme="探针", center_tab=0,
                                       panes=first.panes.state())
        first.manager.mark_all_clean()
        first.close()

        second = make_window(qt_app, ctx)
        try:
            second.show()
            qt_app.processEvents()
            assert second.panes.outer.sizes() == want
        finally:
            second.manager.mark_all_clean()
            second.close()

    def test_collapsed_pane_round_trips(self, qt_app, ctx):
        """收起的窗格重启后还得是收起的 —— 否则空的左窗格每次都会重新占位。"""
        ctx.manifest = self._manifest()
        first = make_window(qt_app, ctx)
        first.panes.pane("right").set_collapsed(True)
        first.ctx.settings.save_window(first, theme="探针", center_tab=0,
                                       panes=first.panes.state())
        first.manager.mark_all_clean()
        first.close()

        second = make_window(qt_app, ctx)
        try:
            assert second.panes.pane("right").is_collapsed()
            assert not second.panes.pane("bottom").is_collapsed()
        finally:
            second.manager.mark_all_clean()
            second.close()

    def test_corrupt_pane_state_does_not_break_startup(self, qt_app, ctx):
        ctx.manifest = self._manifest()
        ctx.settings.set_value("window/panes", "{这不是 json")
        window = make_window(qt_app, ctx)
        try:
            assert window.panes.pane("center") is not None
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_reset_layout_clears_what_was_saved(self, qt_app, ctx):
        ctx.manifest = self._manifest()
        window = make_window(qt_app, ctx)
        try:
            window.ctx.settings.save_window(window, theme="探针", center_tab=1,
                                            panes=window.panes.state())
            window.on_reset_layout()
            assert window.ctx.settings.value("window/geometry") in (None, "")
            assert window.ctx.settings.restore_panes() == {}
            assert window.ctx.settings.value("window/state") in (None, "")
            # 主题不是布局的一部分，重置布局不该把它一起抹掉
            assert window.ctx.settings.saved_theme() == "探针"
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_restore_layout_false_ignores_saved_geometry(self, qt_app, ctx):
        """清单说 restore_layout: false 时，存过的几何不许生效。

        拿「同条件下、什么都还没存时」那个尺寸当基准：offscreen 的屏幕只有
        800x800，尺寸会被夹取，硬写清单里的数字是错的。
        """
        from PySide6.QtCore import QSize

        ctx.manifest = load_manifest_text(STUB_MANIFEST, source="<no-restore>")
        baseline = make_window(qt_app, ctx)          # 此刻 settings 还是空的
        expected = QSize(baseline.size())
        baseline.manager.mark_all_clean()
        baseline.close()

        ctx.manifest = self._manifest()              # 会恢复的那份
        saver = make_window(qt_app, ctx)
        saver.resize(700, 600)
        saver.ctx.settings.save_window(saver, theme="探针", center_tab=0)
        saver.manager.mark_all_clean()
        saver.close()

        ctx.manifest = load_manifest_text(STUB_MANIFEST, source="<no-restore>")
        window = make_window(qt_app, ctx)
        try:
            assert window.size() == expected, "存过的几何漏进来了"
        finally:
            window.manager.mark_all_clean()
            window.close()


class TestSubscriptions:
    """模块之间只通过总线话题通信 —— 而话题写在清单里，读 yaml 就知道谁听谁。"""

    def test_subscribed_topic_reaches_on_refresh(self, qt_app, ctx):
        ctx.manifest = load_manifest_text(SUBSCRIBER_MANIFEST, source="<sub>")
        window = make_window(qt_app, ctx)
        try:
            module = window.manager.module("stub.subscriber")
            assert module.payloads == []
            ctx.bus.publish("demo.refreshed", {"n": 1})
            assert module.payloads == [{"n": 1}]
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_unsubscribed_topic_is_ignored(self, qt_app, ctx):
        ctx.manifest = load_manifest_text(SUBSCRIBER_MANIFEST, source="<sub>")
        window = make_window(qt_app, ctx)
        try:
            module = window.manager.module("stub.subscriber")
            ctx.bus.publish("some.other.topic", "x")
            assert module.payloads == []
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_plain_manifest_modules_subscribe_to_nothing(self, window, ctx):
        assert ctx.bus.subscribers("demo.refreshed") == 0


class TestRealManifestBuilds:
    """真清单（config/workbench.yaml）也要能建起来，且每个模块都成功。"""

    def test_shipped_manifest_builds_without_failures(self, qt_app, ctx, tmp_path):
        from ..config import default_manifest_path

        ctx.manifest = load_manifest_text(
            default_manifest_path().read_text(encoding="utf-8"),
            source=str(default_manifest_path()))
        window = make_window(qt_app, ctx)
        try:
            assert window.manager.failures() == {}
            assert {m.module_id for m in window.modules} == {
                "debug.sim_log", "debug.fingerprint", "vms.casemodel",
                "vms.pipeline", "vms.runs", "vms.evidence"}
            assert window.center_tabs.count() == 3      # 仿真日志 + 验证流程 + Case 建模
            titles = [window.center_tabs.tabText(i)
                      for i in range(window.center_tabs.count())]
            # 中央页顺序：业务线 order 优先（debug 10 < vms 30），
            # 同一条线里才轮到模块 order（pipeline 10 < casemodel 20）
            assert titles == ["仿真日志", "验证流程", "Case 建模"]
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_manifest_input_is_loaded_at_startup(self, qt_app, ctx):
        """清单里写了 input，模块启动时就该已经载入那份模型。

        「文件不在就跳过」也是这条规则的一部分 —— 业务输入经常在别的机器上，
        因为找不到数据就不让模块起来，会把「少一份数据」升级成「界面打不开」。
        """
        from ..config import default_manifest_path

        manifest_path = default_manifest_path()
        # manifest_path 也要指到真文件：清单里的 input 是**相对清单所在目录**
        # 解析的，夹具默认给的临时路径会让它解析到 tmp 下去。
        ctx.manifest_path = manifest_path
        ctx.manifest = load_manifest_text(
            manifest_path.read_text(encoding="utf-8"), source=str(manifest_path))

        window = make_window(qt_app, ctx)
        try:
            module = window.manager.module("vms.casemodel")
            assert module.path is not None and module.path.name == "cpu_pipeline.yaml"
            assert module.result is not None
            assert module.result.score.total > 0
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_missing_input_is_skipped_not_fatal(self, qt_app, ctx, tmp_path):
        ctx.manifest = load_manifest_text(
            "groups: [{id: a, title: A}]\n"
            "modules:\n"
            "  - {id: a.sim, title: 甲, group: a, factory: "
            "src.workbench.modules.debug.sim_log:SimLogModule,\n"
            "     input: ../nowhere/missing.yaml}",
            source="<missing-input>")
        window = make_window(qt_app, ctx)
        try:
            assert window.manager.failures() == {}       # 模块照常起来
            assert window.manager.module("a.sim") is not None
        finally:
            window.manager.mark_all_clean()
            window.close()


class TestRealModulesBehave:
    """垂直切片的两个真模块：按钮回调真的把工具跑通、结果铺进表格。"""

    @staticmethod
    def _window(qt_app, ctx):
        from ..config import default_manifest_path

        ctx.manifest = load_manifest_text(
            default_manifest_path().read_text(encoding="utf-8"),
            source=str(default_manifest_path()))
        return make_window(qt_app, ctx)

    def test_sim_log_parses_pasted_text(self, qt_app, ctx):
        window = self._window(qt_app, ctx)
        try:
            module = window.manager.module("debug.sim_log")
            module.editor.setPlainText(
                "UVM_ERROR @ 1250ns: tb.sv(128) | mismatched: 3\n"
                "driven: 40\n[SCB_LOOP] matched=37 mismatched=3")
            module.parse_pasted()
            assert "FAIL" in module.summary.text()
            row_keys = [row["键"] for row in module.model.rows]
            assert "driven" in row_keys and "errors" in row_keys
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_sim_log_scan_of_missing_dir_shows_the_tool_message(self, qt_app, ctx):
        """目录不存在时工具自己会给一句人话 —— 界面要原样呈现，不要吞掉。"""
        window = self._window(qt_app, ctx)
        try:
            module = window.manager.module("debug.sim_log")
            module.dir_edit.setText("definitely-not-a-real-dir")
            module.scan_output_dir()
            assert "not found" in module.banner.text()
            assert module.model.rowCount() == 0
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_fingerprint_renders_rows(self, qt_app, ctx):
        window = self._window(qt_app, ctx)
        try:
            module = window.manager.module("debug.fingerprint")
            module.editor.setPlainText("ERROR: tb.sv(42): Undefined variable foo")
            module.take_fingerprint()
            assert "指纹" in module.summary.text()
            assert module.model.rowCount() > 0
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_fingerprint_refuses_empty_input(self, qt_app, ctx):
        window = self._window(qt_app, ctx)
        try:
            module = window.manager.module("debug.fingerprint")
            module.editor.setPlainText("   ")
            module.take_fingerprint()
            assert module.banner.is_showing
            assert module.model.rowCount() == 0
        finally:
            window.manager.mark_all_clean()
            window.close()
