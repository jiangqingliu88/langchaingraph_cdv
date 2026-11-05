"""模块管理器 —— 清单怎么落成标签页 / Dock / 菜单。

用 `stub_modules` 里的假模块：清单到界面的这条路不该依赖真模块能不能 import。
"""
from __future__ import annotations

from PySide6.QtWidgets import QMdiArea, QPlainTextEdit

from ..manifest import load_manifest_text
from .conftest import (BROKEN_MANIFEST, DIRTY_MANIFEST, STUB_MANIFEST,
                       SUBSCRIBER_MANIFEST, make_window, window_menu_entry)


def expected_center_order(window) -> list:
    """清单里 center 模块的顺序 —— 懒加载下"点开的顺序"应当照它来。"""
    from ..ui.containers.workspace import PANE_AREAS  # noqa: F401  （契约来源，留个引用）

    return [spec.id for spec in window.ctx.manifest.modules_in("center")]


class TestBuild:
    def test_mdi_is_empty_until_you_open_something(self, window):
        """**工作区默认是空的** —— 不在启动时把中心模块都铺出来。

        模块实例是建好的（它们的菜单动作要靠它），但控件留在 manager 手里
        没进工作区；点一下才"加载视图"（见 `ModuleManager.open`）。
        """
        assert window.workspace.subwindow_count() == 0
        assert window.manager.module("stub.center") is not None   # 实例在
        assert not window.manager.is_open("stub.center")          # 视图没加载

    def test_opening_loads_the_view_and_repeat_click_does_not_duplicate(self, window):
        assert window.manager.open("stub.center") is True
        assert window.workspace.subwindow_count("stub.center") == 1
        assert window.manager.open("stub.center") is True
        assert window.workspace.subwindow_count("stub.center") == 1  # 不重复建

    def test_center_subwindows_follow_the_order_you_open_them(self, window):
        """桩清单里 vms 那页的模块 order 更小，但 debug 业务线排在前面 ——
        这个顺序在清单里；工作区里出现的顺序则跟着**你点的顺序**。
        """
        for mid in ("stub.center", "stub.center2"):
            window.manager.open(mid)
        assert window.workspace.ordered_module_ids() == ["stub.center", "stub.center2"]

    def test_same_area_modules_land_in_the_same_dock_area(self, window):
        """同区模块共享一块 dock 区 —— Qt 会把它们叠成一组页签。"""
        assert window.manager.pane_of("stub.dock_a") == "bottom"
        assert window.manager.pane_of("stub.dock_b") == "bottom"
        assert {"stub.dock_a", "stub.dock_b"} <= set(
            window.workspace.modules_in("bottom"))

    def test_dock_widget_carries_the_module_id(self, window):
        """dock 控件身上带着 module_id —— 平台靠它认人（标题、聚焦、显隐）。"""
        dock = window.workspace.dock_of("stub.dock_b")
        assert dock.widget().property("module_id") == "stub.dock_b"

    def test_every_module_is_reachable_by_id(self, window):
        assert window.manager.module("stub.center").title == "中央页"
        assert window.manager.module("nope") is None
        assert {m.module_id for m in window.modules} == {
            "stub.center", "stub.center2", "stub.dock_a", "stub.dock_b"}

    def test_group_filtering_on_modules(self, window):
        assert {m.module_id for m in window.manager.modules("debug")} == {
            "stub.center", "stub.dock_a", "stub.dock_b"}
        assert window.manager.modules("nope") == []

    def test_module_actions_are_not_all_dumped_on_the_toolbar(self, window, qt_app):
        """**模块动作不在启动时全挂上工具栏** —— 那是按上下文挂的（见下一条）。

        全挂上去的后果实测过：25 个模块里有 5 个带动作，其中两个各有一套
        「保存 / 另存为 / 立即校验」，于是工具栏上出现两组同名按钮，总长还超出
        窗口被截断（1520 宽也放不下，右边挂一个溢出箭头）。
        """
        toolbar_texts = [a.text() for a in window.toolbar.actions()]
        assert "假动作" not in toolbar_texts
        assert "载入清单…" in toolbar_texts          # 全局那几条常驻

    def test_module_actions_follow_the_active_module(self, window, qt_app):
        """激活哪个模块，工具栏才挂哪个模块的动作；切走就换掉。

        带动作的是 `stub.center2`（清单里那条），别拿 `stub.center` 试 ——
        它没有动作，断言会一直假过。
        """
        window.show()
        assert window.manager.focus("stub.center2")
        qt_app.processEvents()
        assert "假动作" in [a.text() for a in window.toolbar.actions()]

        assert window.manager.focus("stub.center")
        qt_app.processEvents()
        texts = [a.text() for a in window.toolbar.actions()]
        assert "假动作" not in texts
        assert "载入清单…" in texts               # 全局那几条不受影响
        assert "载入清单…" in [a.text() for a in window.toolbar.actions()]


class TestFocus:
    def test_focus_activates_the_center_subwindow(self, window, qt_app):
        # 标签页模式下 Qt 要靠真实布局才有"当前标签" —— 不 show 的话
        # `activeSubWindow()` 拿不到东西（窗口都没显示，谈何激活）
        window.show()
        assert window.manager.focus("stub.center2")
        qt_app.processEvents()
        assert window.workspace.active_module_id() == "stub.center2"

    def test_focus_raises_the_dock(self, window):
        """不光要返回 True —— 得真的把它抬起来。只断言返回值的话，实现改成
        「找到了但没切」也照样通过。"""
        assert window.manager.focus("stub.dock_a")
        dock = window.workspace.dock_of("stub.dock_a")
        assert dock is not None and not dock.isHidden()

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
            window.manager.open("stub.center")
            window.manager.open("stub.broken")
            titles = [s.windowTitle() for s in window.mdi.subWindowList()]
            assert "中央页" in titles
            assert "坏模块" in titles          # 占位窗口仍然出现，让人看见它坏了
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_the_broken_tab_shows_the_traceback(self, qt_app, ctx):
        window = self._broken(qt_app, ctx)
        try:
            window.manager.open("stub.broken")
            sub = next(s for s in window.mdi.subWindowList()
                       if s.windowTitle() == "坏模块")
            widget = sub.widget()
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
            assert window.workspace.contains("stub.broken_dock")
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
        first.ctx.settings.save_window(first, theme="探针")
        first.manager.mark_all_clean()
        first.close()

        second = make_window(qt_app, ctx)
        try:
            assert second.size() == QSize(500, 400)
            assert second.pos() == QPoint(30, 40)
        finally:
            second.manager.mark_all_clean()
            second.close()

    def test_subwindow_geometry_round_trips(self, qt_app, ctx):
        """子窗口的位置与大小存得下、贴得回。

        （分割条时代这条测的是 splitter 尺寸数组；`QMdiArea` **没有**
        `saveState()` —— 那份快照是 `Workspace` 自己拼的，所以这里也换成
        手工存的几何往返。）
        """
        ctx.manifest = self._manifest()
        first = make_window(qt_app, ctx)
        # **标签页模式下 Qt 会把子窗口铺满整块区域，几何没有意义** ——
        # 要测"位置存得下贴得回"得先切到子窗口模式。
        first.workspace.set_view_mode(False)
        first.manager.open("stub.center")          # 懒加载：先点开才谈得上几何
        first.show()
        qt_app.processEvents()
        first.workspace.subwindows_of("stub.center")[0].setGeometry(60, 70, 520, 430)
        qt_app.processEvents()
        docks, subs = first.workspace.save_layout()
        first.ctx.settings.save_dock_state(docks)
        first.ctx.settings.save_mdi_state(subs)
        first.manager.mark_all_clean()
        first.close()

        second = make_window(qt_app, ctx)
        try:
            second.workspace.set_view_mode(False)
            second.manager.open("stub.center")
            second.show()
            qt_app.processEvents()
            geo = second.workspace.subwindows_of("stub.center")[0].geometry()
            assert (geo.x(), geo.y(), geo.width(), geo.height()) == (60, 70, 520, 430)
        finally:
            second.manager.mark_all_clean()
            second.close()

    def test_hidden_module_round_trips(self, qt_app, ctx):
        """关掉的模块重启后还是关的 —— 否则每次启动都得手动再关一遍。"""
        ctx.manifest = self._manifest()
        first = make_window(qt_app, ctx)
        second_module = [m for m in ctx.manifest.modules_in("center")
                         if m.id != "stub.center"][0].id
        first.manager.set_visible(second_module, False)
        assert not first.workspace.contains(second_module)
        docks, subs = first.workspace.save_layout()
        first.ctx.settings.save_dock_state(docks)
        first.ctx.settings.save_mdi_state(subs)
        first.manager.mark_all_clean()
        first.close()

        second = make_window(qt_app, ctx)
        try:
            assert not second.workspace.contains(second_module)
        finally:
            second.manager.mark_all_clean()
            second.close()

    def test_corrupt_layout_state_does_not_break_startup(self, qt_app, ctx):
        """布局存坏了不该让界面起不来 —— dock 的二进制与子窗口的 JSON 都试一遍。"""
        ctx.manifest = self._manifest()
        ctx.settings.set_value("window/mdi", "{这不是 json")
        ctx.settings.set_value("window/docks", "垃圾字节")
        window = make_window(qt_app, ctx)
        try:
            assert window.manager.open("stub.center") is True
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_stale_layout_is_ignored(self, qt_app, ctx):
        """**换了外壳形状之后，旧布局必须作废。**

        踩过的坑：MDI/dock 改造后，注册表里那份"两个 dock 并排"的旧布局被
        无条件贴回，把新壳的同区 tabify 覆盖掉 —— 用户看不到切换标签条，
        还以为是功能没做。修法是布局版本号：旧壳没写过这个 key，于是判为过时。
        """
        ctx.manifest = self._manifest()
        saver = make_window(qt_app, ctx)
        saver.ctx.settings.save_dock_state(saver.workspace.save_layout()[0])
        saver.manager.mark_all_clean()
        saver.close()
        # 模拟"旧版本留下的状态"：把版本号抹掉
        ctx.settings._settings.remove("window/layout_version")   # noqa: SLF001
        ctx.settings.sync()
        assert not ctx.settings.layout_is_current()

        window = make_window(qt_app, ctx)
        try:
            # 这份桩清单的底区有控制台 + 两个 stub dock —— 它们该叠成一组
            bottom = window.workspace.modules_in("bottom")
            assert len(bottom) >= 2, bottom
            first, second = (window.workspace.dock_of(m) for m in bottom[:2])
            assert second in window.tabifiedDockWidgets(first)
            assert first in window.tabifiedDockWidgets(second)
        finally:
            window.manager.mark_all_clean()
            window.close()

    def test_current_layout_is_restored(self, qt_app, ctx):
        """版本号对得上就照贴 —— 用户自己摆的布局当然要记住。"""
        ctx.manifest = self._manifest()
        saver = make_window(qt_app, ctx)
        saver.ctx.settings.save_dock_state(saver.workspace.save_layout()[0])
        saver.ctx.settings.mark_layout_version()
        saver.manager.mark_all_clean()
        saver.close()

        assert ctx.settings.layout_is_current()

    def test_startup_is_always_empty(self, qt_app, ctx):
        """**启动就是空的** —— 上次开着的视图也不自动开回来。

        恢复的只有**布局**（dock 停靠与显隐、各视图的位置尺寸），不是
        "打开了哪些"。一个都没点就自己冒出一堆标签，反而不知道哪些是要看的。
        """
        ctx.manifest = self._manifest()
        first = make_window(qt_app, ctx)
        first.workspace.set_view_mode(True)          # 连视图模式都改一下
        for mid in ("stub.center", "stub.center2"):
            first.manager.open(mid)
        assert first.workspace.subwindow_count() == 2
        first.manager.mark_all_clean()
        first.close()

        second = make_window(qt_app, ctx)
        try:
            assert second.workspace.subwindow_count() == 0        # 空的
            assert second.workspace.ordered_module_ids() == []
        finally:
            second.manager.mark_all_clean()
            second.close()

    def test_closing_the_window_re_docks_floating_panels(self, qt_app, ctx):
        """浮出来的面板是**独立的顶层窗口** —— 主窗口关掉时它不会自己跟着关。

        不收回来的话：关掉主程序后它还留在桌面上，进程也退不干净
        （实测：`win.close()` 之后仍有一个可见的顶层窗口）。
        """
        ctx.manifest = self._manifest()
        window = make_window(qt_app, ctx)
        window.show()
        dock = window.workspace.dock_of("stub.dock_a")
        dock.setFloating(True)
        qt_app.processEvents()
        assert dock.isFloating()

        window.close()
        qt_app.processEvents()
        assert not dock.isFloating()
        assert not dock.isVisible()

    def test_reset_layout_clears_what_was_saved(self, qt_app, ctx):
        ctx.manifest = self._manifest()
        window = make_window(qt_app, ctx)
        try:
            docks, subs = window.workspace.save_layout()
            window.ctx.settings.save_window(window, theme="探针")
            window.ctx.settings.save_dock_state(docks)
            window.ctx.settings.save_mdi_state(subs)
            window.on_reset_layout()
            assert window.ctx.settings.value("window/geometry") in (None, "")
            assert window.ctx.settings.restore_dock_state() is None
            assert window.ctx.settings.restore_mdi_state() == ""
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
        saver.ctx.settings.save_window(saver, theme="探针")
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
            # 46 = 31 个专业模块 + 项目入口 2 + SoC 5 + IP 3 + 工程服务 3
            #      + 环境与工具 1 + 测试点表（xlsx）1
            assert len(window.modules) == 46
            assert {m.module_id for m in window.modules} >= {
                "project.overview", "project.management",
                "soc.overview", "soc.architecture", "soc.verification",
                "soc.c_cases", "soc.signoff",
                "ip.catalog", "ip.workspace", "ip.signoff",
                "service.uvm", "service.regression", "service.coverage",
                "platform.settings",
                "design.output", "model.output", "ops.output", "ops.regression_status",
                "ops.regression_wave", "ops.regression_coverage",
                "coverage.output",
                "audit.output", "ide.manual_nodes", "flow.compare", "debug.sim_log",
                "debug.fingerprint", "debug.output", "verify.output",
                "verify.casemodel", "coverage.excludes",
                "flow.pipeline", "flow.todo", "flow.drafts", "flow.runs", "flow.evidence",
                "flow.task", "flow.diagram", "flow.artifacts", "flow.fcov", "flow.signoff",
                "flow.trend", "flow.decision", "flow.manifest"}
            # **工作区默认是空的**：实例都建好了，但没一个进 MDI
            assert window.workspace.subwindow_count() == 0

            # 按清单顺序逐个点开 —— 打开的顺序就是清单顺序（业务线 order 优先，
            # 同一条线里才轮到模块 order：design 10 < model 20 < verify 30
            # < ops 40 < coverage 50 < debug 60 < audit 70 < ide 80 < flow 90）
            want = ["项目总览", "项目管理",
                    "SoC 总览", "SoC 架构", "SoC 验证工作区", "SoC C 用例",
                    "SoC 签核",
                    "IP 目录", "IP 工作区", "IP 发布检查",
                    "UVM 自动化验证", "回归效率优化", "Coverage Closure",
                    "IP 规格", "人工节点", "测试点表（xlsx）",
                    # 工程工作区（order 8）排在运行时之前 —— 它是入口。
                    # 线内顺序按"用法"：起（验证流程）→ 选（运行历史，左窗格）→
                    # 看（任务总览/流程视图/运行对比）→ 材料（产物审查/证据）→
                    # 判（签核判定/运行清单）→ 回头查（决策轨迹/进度趋势/跟踪表）
                    "验证流程", "待办 / 卡点", "任务总览", "流程视图", "运行对比",
                    "产物审查", "签核判定", "运行清单", "规则草案", "功能覆盖率",
                    "决策轨迹", "进度趋势",
                    "设计产出", "模型产出", "验证产出",
                    # ISA 激励归 verify 线（order 30 > Case 建模 20）：先声明测什么，
                    # 再把它铺成指令流。清单里的位置已与 `group: verify` 对齐。
                    "Case 建模", "ISA 激励",
                    "回归产出", "回归状态", "回归波形", "回归覆盖率",
                    "覆盖率产出", "覆盖率豁免",
                    "仿真日志", "调试产出", "签核产出",
                    "环境与工具"]
            for module_id in expected_center_order(window):
                window.manager.open(module_id)
            titles = [s.windowTitle() for s in window.mdi.subWindowList(
                QMdiArea.WindowOrder.CreationOrder)]
            assert titles == want
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
            module = window.manager.module("verify.casemodel")
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
