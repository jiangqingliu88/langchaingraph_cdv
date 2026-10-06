"""七条 agent 线的产出总览。

七个模块共用同一个视图基类（`modules/agent_output.py`）、同一个绑定
（`agent.outputs`），只有 `ROLE` 不同。测试打桩 `run_tool` 这一层，
于是 `load()` 的真实路径被完整覆盖。

同时钉住「一条线一个文件、`group` 与目录一致」这条约定 —— 那是把共享视图
拆成七个几行子类的唯一理由。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

#: 角色 → (模块 id, 工厂类路径, 期望的标题)
LINES = {
    "design":   ("design.output",   "src.workbench.modules.design.output",   "设计产出"),
    "model":    ("model.output",    "src.workbench.modules.model.output",    "模型产出"),
    "verify":   ("verify.output",   "src.workbench.modules.verify.output",   "验证产出"),
    "ops":      ("ops.output",      "src.workbench.modules.ops.output",      "回归产出"),
    "coverage": ("coverage.output", "src.workbench.modules.coverage.output", "覆盖率产出"),
    "debug":    ("debug.output",    "src.workbench.modules.debug.output",    "调试产出"),
    "audit":    ("audit.output",    "src.workbench.modules.audit.output",    "签核产出"),
}

EVENTS = [
    {"seq": 1, "kind": "stage.finished", "stage": "design", "agent": "design",
     "title": "规格与设计", "round": 0, "status": "ok", "duration_s": 12.5,
     "payload": {"delta": {"design_arch": {}}}},
    {"seq": 2, "kind": "stage.finished", "stage": "ops", "agent": "ops",
     "title": "编译与仿真回归", "round": 1, "status": "ok", "duration_s": 30.0,
     "payload": {"passed": 3, "delta": {"regression": {"passed": 3}}}},
]


def _run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "apb_uart"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "rtl").mkdir(exist_ok=True)
    (root / "sim").mkdir(exist_ok=True)
    (root / "rtl" / "apb_uart.sv").write_text("module m; endmodule\n", encoding="utf-8")
    (root / "sim" / "run.log").write_text("PASS\n", encoding="utf-8")
    (root / "docs" / "run_events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in EVENTS), encoding="utf-8")
    return root


def _spec(module_id: str):
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    return next(s for s in manifest.modules if s.id == module_id), manifest, manifest_path


def _patch(module, run_dir) -> None:
    from src.tools.flow_tools import run_agent_outputs

    def fake_run_tool(name=None, *, quiet=False, force=False, **kwargs):
        tool = name or (module.spec.tool.name if module.spec.tool else None)
        if tool == "pipeline.detail":
            return {"dir": str(run_dir)}
        if tool == "agent.outputs":
            return run_agent_outputs(str(run_dir), str(kwargs.get("role", "")))
        raise AssertionError(f"没打桩的工具：{tool}")

    module.run_tool = fake_run_tool


def _make(qt_app, settings, role: str):
    from .conftest import make_ctx
    from src.workbench.loader import resolve

    module_id, factory, _title = LINES[role]
    spec, manifest, manifest_path = _spec(module_id)
    cls = resolve(f"{factory}:{role.capitalize()}OutputModule")
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = cls(ctx, spec)
    widget = mod.create_widget()
    return mod, widget


@pytest.fixture
def design(qt_app, settings, tmp_path):
    mod, widget = _make(qt_app, settings, "design")
    _patch(mod, _run_dir(tmp_path))
    mod.load("run-1")
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


class TestRendering:
    def test_stages_table_filled(self, design):
        assert design.stage_model.rowCount() == 1
        assert design.stage_model.rows[0]["title"] == "规格与设计"
        assert design.stage_model.rows[0]["duration"] == "12.5s"

    def test_artifacts_table_filled(self, design):
        assert design.artifact_model.rowCount() == 1
        assert design.artifact_model.rows[0]["title"] == "RTL"
        assert design.artifact_model.rows[0]["count"] == "1"
        assert "apb_uart.sv" in design.artifact_model.rows[0]["files"]

    def test_header_and_counts(self, design):
        assert "run-1" in design.header_label.text()
        assert "设计构建" in design.header_label.text()
        assert "1 个阶段" in design.count_label.text()
        assert "1 个产物文件" in design.count_label.text()


class TestPerRole:
    def test_ops_sees_its_own_stage_and_dirs(self, qt_app, settings, tmp_path):
        mod, widget = _make(qt_app, settings, "ops")
        try:
            _patch(mod, _run_dir(tmp_path))
            mod.load("run-1")
            assert [s["title"] for s in mod.stage_model.rows] == ["编译与仿真回归"]
            assert [a["title"] for a in mod.artifact_model.rows] == ["仿真 / 回归"]
            assert "passed=3" in mod.stage_model.rows[0]["summary"]
        finally:
            widget.deleteLater()
            qt_app.processEvents()

    def test_role_without_dirs_notes_it(self, qt_app, settings, tmp_path):
        mod, widget = _make(qt_app, settings, "debug")
        try:
            _patch(mod, _run_dir(tmp_path))
            mod.load("run-1")
            assert mod.artifact_model.rowCount() == 0
            assert "没有 debug 的痕迹" in mod.note_label.text()
        finally:
            widget.deleteLater()
            qt_app.processEvents()

    @pytest.mark.parametrize("role", sorted(LINES))
    def test_every_line_builds_and_declares_its_role(self, qt_app, settings, role):
        mod, widget = _make(qt_app, settings, role)
        try:
            assert mod.role == role
            assert mod.spec.group == role        # 目录名 == group == ROLE
            assert mod.title == LINES[role][2]
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestBeforeSelection:
    def test_placeholder_before_any_run(self, qt_app, settings):
        mod, widget = _make(qt_app, settings, "design")
        try:
            assert "还没选中运行" in mod.header_label.text()
            assert mod.stage_model.rowCount() == 0
        finally:
            widget.deleteLater()
            qt_app.processEvents()

    def test_empty_run_id_is_a_noop(self, qt_app, settings):
        mod, widget = _make(qt_app, settings, "design")
        try:
            mod.load("")
            assert mod.run_id == ""
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestWiring:
    def test_all_seven_share_one_binding(self):
        from ..bridge.catalog import by_name
        binding = by_name("agent.outputs")
        assert binding is not None
        assert binding.pure is True
        assert binding.kind == "json"

    @pytest.mark.parametrize("role", sorted(LINES))
    def test_each_line_subscribes_to_run_selection(self, role):
        spec, _m, _p = _spec(LINES[role][0])
        assert "run.selected" in spec.params.get("subscribe", [])

    def test_factory_path_matches_the_group_directory(self):
        """`group: ops` ⇒ 代码在 `modules/ops/`。把共享视图拆成七个子类就是为了这个。"""
        for role, (module_id, factory, _title) in LINES.items():
            spec, _m, _p = _spec(module_id)
            assert spec.factory.startswith(f"src.workbench.modules.{spec.group}."), spec.id
            assert factory == f"src.workbench.modules.{role}.output"
