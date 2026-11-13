"""流程与证据线的两个新视图：决策轨迹、运行清单。

都是「选一次运行 → 读运行目录 → 填表」。测试打桩 `run_tool`，覆盖真实 `load()`。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

EVENTS = [
    {"seq": 1, "kind": "stage.finished", "stage": "coverage", "agent": "coverage",
     "title": "覆盖率", "round": 1, "status": "ok", "duration_s": 1.0,
     "payload": {"delta": {"sim_reward": {
         "total": 0.8125, "weakest": "coverage"}}}},
    {"seq": 2, "kind": "stage.finished", "stage": "decide", "agent": "coverage",
     "title": "决策", "round": 1, "status": "ok", "duration_s": 0.3,
     "payload": {"delta": {"pending_action": {
         "action_type": "GENERATE_DIRECTED_TEST", "reason": "功能覆盖 62%",
         "priority": 2, "params": {"dimension": "D_baud"},
         "source": "rl_suggested"}}}},
    {"seq": 3, "kind": "stage.finished", "stage": "governor", "agent": "",
     "title": "驾驭", "round": 1, "status": "ok", "duration_s": 0.1,
     "payload": {"delta": {"governance_outcome": "proceed"}}},
]


def _run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "apb_uart"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "run_events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in EVENTS), encoding="utf-8")
    (root / "docs" / "manifest.json").write_text(json.dumps(
        {"architecture": "closed_loop_7agents", "run_id": "apb_uart", "iterations": 4,
         "final_coverage": 93.0, "generator": "vagent dump",
         "manifest_hash": "abc123", "evidence_hash": "def456",
         "rtl_hashes": {"apb_uart.sv": "9f2c"}}, ensure_ascii=False), encoding="utf-8")
    (root / "docs" / "file_change_chain.json").write_text(json.dumps(
        {"changes": [{"seq": 1, "agent": "design",
                      "file": "rtl/apb_uart.sv", "reason": "生成 RTL"}]},
        ensure_ascii=False), encoding="utf-8")
    return root


def _spec(module_id: str):
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    return next(s for s in manifest.modules if s.id == module_id), manifest, manifest_path


def _patch(module, run_dir) -> None:
    from src.interfaces.api.flow import run_decision_trace, run_manifest_info

    def fake_run_tool(name=None, *, quiet=False, force=False, **kwargs):
        tool = name or (module.spec.tool.name if module.spec.tool else None)
        if tool == "pipeline.detail":
            return {"dir": str(run_dir)}
        if tool == "flow.decision":
            return run_decision_trace(str(run_dir))
        if tool == "flow.manifest":
            return run_manifest_info(str(run_dir))
        raise AssertionError(f"没打桩的工具：{tool}")

    module.run_tool = fake_run_tool


def _make(qt_app, settings, module_id: str, cls_name: str):
    from .conftest import make_ctx
    from src.workbench.loader import resolve

    spec, manifest, manifest_path = _spec(module_id)
    factory = spec.factory.split(":")[0]
    cls = resolve(f"{factory}:{cls_name}")
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = cls(ctx, spec)
    widget = mod.create_widget()
    return mod, widget


@pytest.fixture
def decision(qt_app, settings, tmp_path):
    mod, widget = _make(qt_app, settings, "flow.decision", "DecisionTraceModule")
    _patch(mod, _run_dir(tmp_path))
    mod.load("run-1")
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


@pytest.fixture
def manifest_view(qt_app, settings, tmp_path):
    mod, widget = _make(qt_app, settings, "flow.manifest", "ManifestModule")
    _patch(mod, _run_dir(tmp_path))
    mod.load("run-1")
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


class TestDecisionTrace:
    def test_round_row_filled(self, decision):
        assert decision.model.rowCount() == 1
        row = decision.model.rows[0]
        assert row["round"] == 1
        assert row["action"] == "GENERATE_DIRECTED_TEST"
        assert row["governance"] == "proceed"
        assert row["reason"] == "功能覆盖 62%"
        assert row["source"] == "rl_suggested"
        assert row["source_label"] == "RL 采纳"
        assert row["reward"] == "0.8125（最弱 coverage）"

    def test_params_are_joined(self, decision):
        assert decision.model.rows[0]["params"] == "dimension=D_baud"

    def test_note_counts_rounds(self, decision):
        assert "轮决策" in decision.note_label.text()

    def test_missing_journal_says_so(self, qt_app, settings, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        mod, widget = _make(qt_app, settings, "flow.decision", "DecisionTraceModule")
        try:
            _patch(mod, empty)
            mod.load("run-2")
            assert mod.model.rowCount() == 0
            assert "运行日志" in mod.note_label.text()
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestManifestView:
    def test_manifest_table_filled(self, manifest_view):
        assert manifest_view.manifest_model.rowCount() > 0
        keys = [r["key"] for r in manifest_view.manifest_model.rows]
        assert "架构" in keys and "RTL 文件哈希" in keys

    def test_hashes_shown(self, manifest_view):
        text = manifest_view.hash_label.text()
        assert "abc123" in text and "def456" in text

    def test_change_chain_filled(self, manifest_view):
        assert manifest_view.chain_model.rowCount() == 1
        assert manifest_view.chain_model.rows[0]["agent"] == "design"
        assert manifest_view.chain_model.rows[0]["file"] == "rtl/apb_uart.sv"

    def test_missing_manifest_says_so(self, qt_app, settings, tmp_path):
        empty = tmp_path / "empty2"
        empty.mkdir()
        mod, widget = _make(qt_app, settings, "flow.manifest", "ManifestModule")
        try:
            _patch(mod, empty)
            mod.load("run-3")
            assert mod.manifest_model.rowCount() == 0
            assert "还没收尾" in mod.hash_label.text()
            assert "manifest.json" in mod.note_label.text()
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestWiring:
    @pytest.mark.parametrize("binding", ["flow.decision", "flow.manifest"])
    def test_bindings_registered_and_pure(self, binding):
        from ..bridge.catalog import by_name
        b = by_name(binding)
        assert b is not None and b.pure is True and b.kind == "json"

    @pytest.mark.parametrize("module_id", ["flow.decision", "flow.manifest"])
    def test_subscribes_and_grouped(self, module_id):
        spec, _m, _p = _spec(module_id)
        assert spec.group == "flow"
        assert "run.selected" in spec.params.get("subscribe", [])
