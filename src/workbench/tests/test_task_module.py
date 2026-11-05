"""验证任务总览模块。

打桩 `run_tool`，让真实 `load()` 路径被覆盖。断言的是「一屏能不能说清情况」：
顶部那行总览、指标表、卡点表。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

MODULE_ID = "flow.task"
FINISHED_BAD = {
    "target": 95.0, "final_coverage": 62.0, "effective_coverage": 62.0,
    "converged": False, "iterations": 2,
    "phases": [{"name": "ops", "status": "failed", "score": 0}],
    "planning": {"convergence_forecast": {"rounds_to_target": float("inf"),
                                          "converging": False}},
}
EVENTS = [
    {"seq": 1, "kind": "coverage.updated", "round": 1, "payload": {"total": 62.0}},
    {"seq": 2, "kind": "stage.failed", "stage": "ops", "title": "编译与仿真回归",
     "round": 2, "payload": {"error": "vlog 报错 3 处"}},
]


def _run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "apb_uart"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "run_events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in EVENTS), encoding="utf-8")
    (root / "docs" / "manifest.json").write_text(
        json.dumps(FINISHED_BAD, ensure_ascii=False), encoding="utf-8")
    return root


def _spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    return (next(s for s in manifest.modules if s.id == MODULE_ID),
            manifest, manifest_path)


def _patch(module, run_dir) -> None:
    from src.app.services.flow import run_task

    def fake_run_tool(name=None, *, quiet=False, force=False, **kwargs):
        tool = name or (module.spec.tool.name if module.spec.tool else None)
        if tool == "pipeline.detail":
            return {"dir": str(run_dir)}
        if tool == "flow.task":
            return run_task(str(run_dir))
        raise AssertionError(f"没打桩的工具：{tool}")

    module.run_tool = fake_run_tool


@pytest.fixture
def module(qt_app, settings, tmp_path):
    from .conftest import make_ctx
    from ..modules.flow.task import TaskModule

    spec, manifest, manifest_path = _spec()
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = TaskModule(ctx, spec)
    widget = mod.create_widget()
    _patch(mod, _run_dir(tmp_path))
    mod.load("run-1")
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


def _metric(model, key: str):
    for row in model.rows:
        if row["key"] == key:
            return row["value"]
    raise AssertionError(f"没有指标 {key}")


class TestOverview:
    def test_summary_line_carries_the_run_id_and_state(self, module):
        text = module.summary_label.text()
        assert "run-1" in text
        assert "完成但有错" in text

    def test_target_and_coverage(self, module):
        assert _metric(module.metric_model, "目标覆盖率") == "95%"
        assert _metric(module.metric_model, "当前覆盖率") == "62%"

    def test_gap_is_spelled_out(self, module):
        assert _metric(module.metric_model, "差距") == "还差 33 个点"

    def test_forecast_renders_the_stall_not_infinity(self, module):
        """`inf` 不能漏到界面上 —— 这里显示成人话。"""
        text = _metric(module.metric_model, "收敛预测")
        assert "停滞" in text
        assert "inf" not in text.lower()

    def test_phase_counts(self, module):
        assert _metric(module.metric_model, "阶段") == "0/1 过，1 失败"

    def test_rounds_curve(self, module):
        assert _metric(module.metric_model, "逐轮覆盖率") == "R1 62%"

    def test_current_step_from_the_last_event(self, module):
        assert "编译与仿真回归" in _metric(module.metric_model, "当前步骤")


class TestBlockers:
    def test_blocker_row_filled(self, module):
        assert module.blocker_model.rowCount() == 1
        assert module.blocker_model.rows[0]["title"] == "编译与仿真回归"
        assert module.blocker_model.rows[0]["round"] == 2      # 原样存 int，显示时转字符串
        assert "vlog 报错" in module.blocker_model.rows[0]["error"]


class TestEmptyAndWiring:
    def test_placeholder_before_selection(self, qt_app, settings):
        from .conftest import make_ctx
        from ..modules.flow.task import TaskModule

        spec, manifest, manifest_path = _spec()
        mod = TaskModule(make_ctx(manifest, manifest_path, settings), spec)
        widget = mod.create_widget()
        try:
            assert "还没选中运行" in mod.summary_label.text()
            assert mod.metric_model.rowCount() == 0
        finally:
            widget.deleteLater()
            qt_app.processEvents()

    def test_empty_run_id_is_a_noop(self, qt_app, settings):
        from .conftest import make_ctx
        from ..modules.flow.task import TaskModule

        spec, manifest, manifest_path = _spec()
        mod = TaskModule(make_ctx(manifest, manifest_path, settings), spec)
        widget = mod.create_widget()
        try:
            mod.load("")
            assert mod.run_id == ""
        finally:
            widget.deleteLater()
            qt_app.processEvents()

    def test_binding_and_group(self):
        from ..bridge.catalog import by_name
        binding = by_name("flow.task")
        assert binding is not None and binding.pure is True
        spec, _m, _p = _spec()
        assert spec.group == "flow"
        assert "run.selected" in spec.params.get("subscribe", [])

    def test_the_line_is_ordered_by_how_you_use_it(self):
        """那条线按**用法**排：起（验证流程）→ 选（运行历史，左窗格）→ 看 → 判 → 回头查。

        第一个是**入口**，不是"最重要的页" —— 没有运行就没有后面的一切，所以
        验证流程打头（order 5），任务总览紧跟（10）回答"这次什么情况"。
        这条钉的是**顺序本身**：改清单顺序它会红，红的时候先想清楚为什么改。
        """
        from .conftest import shipped_manifest
        manifest, _p = shipped_manifest()
        flow_center = [m.id for m in manifest.modules_in("center") if m.group == "flow"]
        assert flow_center[:5] == ["flow.pipeline", "flow.todo", "flow.task",
                                   "flow.diagram", "flow.compare"]
