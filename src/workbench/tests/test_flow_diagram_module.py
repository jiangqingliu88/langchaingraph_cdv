"""流程视图 —— 把闭环画成一张图。

两层各测各的：
  · `FlowMap` 是自绘件（`paintEvent`），纯逻辑可脱离窗口测 —— 结构怎么排、
    状态怎么合并成颜色、截断有没有记账。
  · `DiagramModule` 是它的壳：结构从 `flow.stages` 绑定来（读领域自己的
    `stages.py`），状态从所选运行的日志来。**没选运行就是一片灰**，不编造。

用真清单 + 真绑定，不打桩结构那一路 —— 固定「绑定通、返回形状界面吃得下」。
"""
from __future__ import annotations

import pytest

MODULE_ID = "flow.diagram"


def _shipped_spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    return spec, manifest, manifest_path


@pytest.fixture
def module(qt_app, settings):
    from .conftest import make_ctx
    from ..modules.flow.diagram import DiagramModule

    spec, manifest, manifest_path = _shipped_spec()
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = DiagramModule(ctx, spec)
    widget = mod.create_widget()
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


# ═══════════════════════════════════════════════════════════════
# 自绘件
# ═══════════════════════════════════════════════════════════════

def _model(*, groups=None, loop=None):
    return {"groups": groups or [], "loop": loop or {}}


def _group(gid, title, *nodes):
    return {"id": gid, "title": title,
            "nodes": [{"id": n, "title": n.upper()} for n in nodes]}


class TestFlowMap:
    @staticmethod
    def _chart(qt_app, model=None):
        from ..ui.views.flowmap import FlowMap

        chart = FlowMap()
        if model is not None:
            chart.set_flow(model)
        return chart

    def test_set_flow_keeps_the_structure(self, qt_app):
        chart = self._chart(qt_app, _model(
            groups=[_group("a", "甲", "x")],
            loop={"from": "a", "to": "a"}))
        try:
            assert [g["id"] for g in chart._groups] == ["a"]
            assert chart._loop == {"from": "a", "to": "a"}
        finally:
            chart.deleteLater()

    def test_none_model_is_treated_as_empty(self, qt_app):
        chart = self._chart(qt_app, None)
        try:
            chart.set_flow(None)
            assert chart._groups == [] and chart._loop == {}
        finally:
            chart.deleteLater()

    def test_width_grows_with_group_count(self, qt_app):
        """等宽块横排 —— 组越多图越宽（所以外头套了滚动区）。"""
        one = self._chart(qt_app, _model(groups=[_group("a", "甲", "x")]))
        seven = self._chart(qt_app, _model(
            groups=[_group(f"g{i}", f"第{i}组", "x") for i in range(7)]))
        try:
            assert seven.sizeHint().width() > one.sizeHint().width()
        finally:
            one.deleteLater()
            seven.deleteLater()

    def test_rows_per_box_are_capped(self, qt_app):
        """决策与收敛那组有 12 个节点 —— 全排开会把图撑爆，封顶。"""
        from ..ui.views.flowmap import MAX_NODES_SHOWN

        chart = self._chart(qt_app, _model(
            groups=[_group("big", "大", *[f"n{i}" for i in range(12)])]))
        try:
            assert chart._rows_per_box() == MAX_NODES_SHOWN
        finally:
            chart.deleteLater()

    def test_truncation_reserves_an_extra_row(self, qt_app):
        """被截断时要多留一行放「…还有 N 个」—— 静默吞掉会让人以为这组就这些。"""
        from ..ui.views.flowmap import MAX_NODES_SHOWN

        def height(n):
            chart = self._chart(qt_app, _model(
                groups=[_group("g", "组", *[f"n{i}" for i in range(n)])]))
            try:
                return chart._box_height()
            finally:
                chart.deleteLater()

        assert height(MAX_NODES_SHOWN + 1) > height(MAX_NODES_SHOWN)

    def test_aggregate_is_worst_first(self, qt_app):
        """一组里有失败就整组标红 —— 扫一眼知道卡在哪段，不用逐行读。"""
        chart = self._chart(qt_app, _model(groups=[_group("g", "组", "a", "b")]))
        try:
            chart.set_status({"a": "ok", "b": "failed"})
            assert chart._aggregate(chart._groups[0]) == "failed"
            chart.set_status({"a": "ok", "b": "running"})
            assert chart._aggregate(chart._groups[0]) == "running"
            chart.set_status({"a": "ok"})
            assert chart._aggregate(chart._groups[0]) == "ok"
        finally:
            chart.deleteLater()

    def test_unknown_status_falls_back_to_the_muted_color(self, qt_app):
        """没选运行 / 认不出的状态 —— 用弱色，**不编造**。"""
        from ..ui.views.flowmap import FlowMap
        from ..ui import theme

        assert FlowMap._field_color("") == theme.current().muted
        assert FlowMap._field_color("weird") == theme.current().muted

    def test_known_statuses_map_to_theme_fields(self, qt_app):
        from ..ui.views.flowmap import FlowMap
        from ..ui import theme

        palette = theme.current()
        assert FlowMap._field_color("ok") == palette.ok
        assert FlowMap._field_color("failed") == palette.error
        assert FlowMap._field_color("running") == palette.accent

    def test_soft_color_is_lighter_than_the_solid_one(self, qt_app):
        """块标题条用压淡的底色 —— 直接铺满会把上面的字盖掉。"""
        from PySide6.QtGui import QColor

        from ..ui.views.flowmap import FlowMap

        solid = QColor(FlowMap._field_color("failed"))
        soft = QColor(FlowMap._field_color("failed", soft=True))
        assert soft.lightness() > solid.lightness()

    def test_empty_model_renders_a_hint_instead_of_blank(self, qt_app):
        """没结构时画一句话，别留一片空白 —— 空白会让人以为界面坏了。"""
        from PySide6.QtGui import QPixmap

        chart = self._chart(qt_app, _model())
        try:
            chart.resize(chart.sizeHint())
            pixmap = QPixmap(chart.size())
            chart.render(pixmap)                 # 不抛就算过
            assert not pixmap.isNull()
        finally:
            chart.deleteLater()

    def test_renders_the_real_structure_without_crashing(self, qt_app):
        """真领域的 7 组 + 12 节点的回边都要能画出来。"""
        from PySide6.QtGui import QPixmap

        from ..bridge.adapters import stage_flow

        chart = self._chart(qt_app, stage_flow())
        try:
            chart.set_status({"ops": "running", "coverage": "failed"})
            chart.resize(chart.sizeHint())
            pixmap = QPixmap(chart.size())
            chart.render(pixmap)
            assert not pixmap.isNull()
        finally:
            chart.deleteLater()


# ═══════════════════════════════════════════════════════════════
# 模块
# ═══════════════════════════════════════════════════════════════

class TestStructureFromDomain:
    def test_refresh_draws_the_seven_groups(self, module):
        module.refresh()
        titles = [g["title"] for g in module.chart._groups]
        assert titles == ["流程控制", "设计与建模", "验证构建", "编译与仿真",
                          "覆盖率与调试", "决策与收敛", "审查与签核"]

    def test_loop_back_edge_comes_along(self, module):
        """回边是这个流程最要紧的形状 —— 结构里必须带着它。"""
        module.refresh()
        assert module.chart._loop == {"from": "converge", "to": "exec"}

    def test_structure_has_all_23_nodes(self, module):
        """界面**不另抄一份阶段清单** —— 数出来就该是领域的那 23 个。"""
        module.refresh()
        total = sum(len(g["nodes"]) for g in module.chart._groups)
        assert total == 23


class TestStatusIsNotFabricated:
    def test_without_a_run_everything_is_grey(self, module):
        module.refresh()
        assert module.chart._status == {}
        assert "还没选中运行" in module.count_label.text()

    def test_selecting_a_run_colors_the_stages(self, module, monkeypatch):
        def fake_run_tool(name=None, *, quiet=False, force=False, **kwargs):
            assert name == "pipeline.detail" and kwargs.get("run_id") == "run-1"
            return {"events": [
                {"stage": "init", "kind": "stage.finished", "status": "ok"},
                {"stage": "design", "kind": "stage.finished", "status": "ok"},
                {"stage": "ops", "kind": "stage.started", "status": "running"},
                {"stage": "coverage", "kind": "stage.failed", "status": "failed"},
            ]}

        monkeypatch.setattr(module, "run_tool", fake_run_tool)
        module.on_refresh("run-1")
        assert module.run_id == "run-1"
        assert module.chart._status["ops"] == "running"
        assert module.chart._status["coverage"] == "failed"

    def test_count_label_reports_passed_and_failed(self, module, monkeypatch):
        monkeypatch.setattr(module, "run_tool", lambda *a, **k: {"events": [
            {"stage": "init", "kind": "stage.finished", "status": "ok"},
            {"stage": "design", "kind": "stage.finished", "status": "passed"},
            {"stage": "coverage", "kind": "stage.failed", "status": "failed"},
        ]})
        module.on_refresh("run-2")
        text = module.count_label.text()
        assert "run-2" in text and "2 个阶段已过" in text and "1 个失败" in text

    def test_refresh_reloads_status_for_the_current_run(self, module, monkeypatch):
        """点「刷新」不该把已选运行的状态丢掉。"""
        calls = []

        def fake_run_tool(name=None, *, quiet=False, force=False, **kwargs):
            calls.append(name)
            if name == "pipeline.detail":
                return {"events": [
                    {"stage": "init", "kind": "stage.finished", "status": "ok"}]}
            return None

        monkeypatch.setattr(module, "run_tool", fake_run_tool)
        module.on_refresh("run-3")
        module.refresh()
        assert "pipeline.detail" in calls

    def test_same_run_selected_twice_is_not_reloaded(self, module, monkeypatch):
        calls = []

        def fake_run_tool(name=None, *, quiet=False, force=False, **kwargs):
            calls.append(name)
            return {"events": []}

        monkeypatch.setattr(module, "run_tool", fake_run_tool)
        module.on_refresh("run-4")
        module.on_refresh("run-4")
        assert calls.count("pipeline.detail") == 1

    def test_bad_detail_payload_does_not_wipe_the_chart(self, module, monkeypatch):
        """运行日志读不到时保持原样，别把结构也一起清掉。"""
        module.refresh()
        monkeypatch.setattr(module, "run_tool",
                            lambda *a, **k: {"error": "没有这次运行"})
        module.on_refresh("run-gone")
        assert module.chart._groups                    # 结构还在
        assert module.banner.is_showing                # 但说了话


class TestLiveFollow:
    """运行期间自己跟着日志走 —— 不靠别人的定时器。

    `验证流程` 页是懒加载的：它不开就没有 `run.updated`。所以"进度得自己盯"
    是这一页的必要条件，不是优化。
    """

    @staticmethod
    def _events(run_id, *specs):
        return {"run_id": run_id, "last_seq": max((s[0] for s in specs), default=0),
                "events": [{"seq": s, "stage": st, "kind": k, "status": s2}
                           for s, st, k, s2 in specs]}

    def test_tick_reads_the_journal_incrementally(self, module, monkeypatch):
        module.run_id = "r1"
        seen = []

        def fake(name=None, *, quiet=False, force=False, **kw):
            seen.append((name, kw.get("after_seq")))
            return self._events("r1", (1, "init", "stage.finished", "ok"),
                                (2, "ops", "stage.started", "running"))

        monkeypatch.setattr(module, "run_tool", fake)
        module._tick()
        assert seen == [("pipeline.journal", 0)]      # 从头读一次
        assert module.chart._status == {"init": "ok", "ops": "running"}
        assert module._seq == 2

        module._tick()                                 # 第二次只取新增
        assert seen[-1] == ("pipeline.journal", 2)

    def test_later_events_overwrite_earlier_ones(self, module, monkeypatch):
        module.run_id = "r1"
        monkeypatch.setattr(module, "run_tool", lambda *a, **kw: self._events(
            "r1", (1, "ops", "stage.started", "running")))
        module._tick()
        assert module.chart._status["ops"] == "running"

        monkeypatch.setattr(module, "run_tool", lambda *a, **kw: self._events(
            "r1", (2, "ops", "stage.failed", "failed")))
        module._tick()
        assert module.chart._status["ops"] == "failed"

    def test_no_run_means_no_polling(self, module, monkeypatch):
        called = []
        monkeypatch.setattr(module, "run_tool",
                            lambda *a, **kw: called.append(kw) or {})
        module._tick()
        assert called == []

    def test_a_terminal_event_stops_the_timer(self, module, monkeypatch):
        module.run_id = "r1"
        monkeypatch.setattr(module, "run_tool", lambda *a, **kw: self._events(
            "r1", (1, "finalize", "stage.finished", "ok"),
            (2, "", "run.finished", "ok")))
        module._tick()
        assert module._finished
        assert not module._timer.isActive(), "跑完了还在每秒空转"

    def test_selecting_a_finished_run_does_not_start_a_timer(self, module, monkeypatch):
        monkeypatch.setattr(module, "run_tool", lambda *a, **kw: {
            "state": "completed",
            "events": [{"seq": 1, "stage": "init", "kind": "stage.finished",
                        "status": "ok"}]})
        module._load_status("r-done")
        assert module._finished and not module._timer.isActive()
        assert module.chart._status == {"init": "ok"}

    def test_switching_runs_drops_the_previous_colors(self, module, monkeypatch):
        """换一次运行不能留着上一次的状态 —— 那是两个运行的混合体。"""
        monkeypatch.setattr(module, "run_tool", lambda *a, **kw: {
            "state": "running",
            "events": [{"seq": 1, "stage": "ops", "kind": "stage.failed",
                        "status": "failed"}]})
        module._load_status("r1")
        assert module.chart._status == {"ops": "failed"}

        monkeypatch.setattr(module, "run_tool", lambda *a, **kw: {
            "state": "completed",
            "events": [{"seq": 1, "stage": "init", "kind": "stage.finished",
                        "status": "ok"}]})
        module._load_status("r2")
        assert module.chart._status == {"init": "ok"}

    def test_count_label_marks_a_finished_run(self, module, monkeypatch):
        monkeypatch.setattr(module, "run_tool", lambda *a, **kw: {
            "state": "completed",
            "events": [{"seq": 1, "stage": "init", "kind": "stage.finished",
                        "status": "ok"}]})
        module._load_status("r-done")
        text = module.count_label.text()
        assert "r-done" in text and "1 个阶段已过" in text and "已结束" in text


class TestBinding:
    def test_binding_is_registered_and_pure(self):
        from ..bridge.catalog import by_name

        binding = by_name("flow.stages")
        assert binding is not None
        assert binding.kind == "json"
        assert binding.pure is True

    def test_stage_flow_shape_is_what_the_widget_eats(self):
        from ..bridge.adapters import stage_flow

        model = stage_flow()
        assert [g["id"] for g in model["groups"]] == [
            "control", "design", "verify", "exec", "analysis", "converge", "signoff"]
        assert model["loop"] == {"from": "converge", "to": "exec"}
        first = model["groups"][0]["nodes"][0]
        assert set(first) >= {"id", "title", "agent", "round_scoped"}


# ═══════════════════════════════════════════════════════════════
# 共用件：日志 → 阶段状态
# ═══════════════════════════════════════════════════════════════

class TestStageStatuses:
    def test_latest_status_per_stage_wins(self):
        from ..modules.flow.run_common import stage_statuses

        out = stage_statuses([
            {"stage": "init", "kind": "stage.started", "status": "running"},
            {"stage": "init", "kind": "stage.finished", "status": "ok"},
            {"stage": "ops", "kind": "stage.failed", "status": "failed"},
        ])
        assert out == {"init": "ok", "ops": "failed"}

    def test_events_without_a_stage_are_skipped(self):
        from ..modules.flow.run_common import stage_statuses

        assert stage_statuses([
            {"kind": "run.started", "status": "running"},
            {"kind": "decision", "status": "converge"},
        ]) == {}

    def test_unrelated_kinds_do_not_set_a_status(self):
        """`coverage.updated` 这类事件也带 stage，但它不是阶段的生命周期事件。"""
        from ..modules.flow.run_common import stage_statuses

        assert stage_statuses([
            {"stage": "coverage", "kind": "coverage.updated", "status": "ok"},
        ]) == {}
