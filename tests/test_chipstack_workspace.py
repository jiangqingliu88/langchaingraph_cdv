"""ChipStack 风格产物工作区和跨运行索引（不等同于 Cadence 服务）。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.orchestration_plane.interface_timing_workflow import TemporalSlicePipeline
from src.runtime_plane.artifacts.chipstack_workspace import read_workspace_runs
from src.runtime_plane.tools.execution.interface_timing import SimulationResult
from tests.test_interface_timing_slice import _fixture


def _unavailable(*_args, **_kwargs):
    return SimulationResult("INCOMPLETE", {"simulation_kind": "unavailable"})


def test_project_layout_archive_index_and_not_run_boundaries(tmp_path):
    fixture, _ = _fixture(tmp_path)
    workspace = tmp_path / "chipstack"
    result = TemporalSlicePipeline(fixture, workspace, simulate_backend=_unavailable).run()
    design = fixture.name
    project = workspace / design
    expected = (
        "mental_model_agent",
        "rtl_generation",
        "uvm_agent",
        "simulation_agent",
        "functional_coverage_agent",
        "coverage_closure_agent",
        "dv_debug",
        "formal_agent",
        "rtl_early_estimation_agent",
        "lint_autofix",
        "compile_n_fix",
    )
    for name in expected:
        assert (project / name).is_dir(), name
    for unperformed in ("formal_agent", "rtl_early_estimation_agent", "lint_autofix", "compile_n_fix"):
        status = json.loads((project / unperformed / "status.json").read_text(encoding="utf-8"))
        assert status["status"] == "NOT_RUN"
        assert status["performed"] is False
    assert (workspace / "artifacts.sqlite").is_file()
    assert (workspace / ".cli_logs").is_dir()
    assert (workspace / ".symphony_logs").is_dir()
    assert (workspace / "tui/sessions").is_dir()
    model = (project / "mental_model_agent/mental_model.md").read_text(encoding="utf-8")
    assert "bounded mental model" in model
    assert "Binding: `VALIDATED`" in model
    assert "Specification: `VALIDATED`" in model
    assert (project / "mental_model_agent/provenance.jsonl").is_file()
    assert (project / "rtl_generation/status.json").is_file()
    coverage = json.loads((project / "functional_coverage_agent/coverage.json").read_text(encoding="utf-8"))
    assert all(row["counts"] is None for row in coverage["rows"])
    assert (
        json.loads((project / "coverage_closure_agent/status.json").read_text(encoding="utf-8"))["status"]
        == "INCOMPLETE"
    )
    # 项目 monitor 与 Archive 同一份字节，不能把独立再生或修改藏到另一路。
    archive_monitor = next(workspace.glob("Archive/run-*/monitors/monitor_*.sv"))
    published_monitor = next((project / "uvm_agent/monitors").glob("monitor_*.sv"))
    assert archive_monitor.read_bytes() == published_monitor.read_bytes()
    runs = read_workspace_runs(workspace, design)
    assert len(runs) == 1
    assert runs[0]["overall_status"] == "INCOMPLETE"
    assert runs[0]["simulation_kind"] == "unavailable"
    assert runs[0]["design_name"] == design
    with sqlite3.connect(workspace / "artifacts.sqlite") as connection:
        conn = connection.execute("PRAGMA foreign_key_check")
        assert conn.fetchall() == []
    archived_manifest = next(workspace.glob("Archive/run-*/manifest.json"))
    global_manifest = json.loads((workspace / "run_manifest.json").read_text(encoding="utf-8"))
    assert (workspace / global_manifest["designs"][design]["manifest"]) == archived_manifest
    assert Path(result["evidence_manifest"]) == archived_manifest
    assert result["workspace"]["project_root"] == str(project)
    for path in (project / "run_manifest.json", archived_manifest):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["workspace"]["schema"] == "chipstack_workspace_v1"
    # 本机缺 EDA，只有状态证据，不伪造波形。
    assert not list(workspace.rglob("*.vcd"))


def test_workspace_preserves_rerun_history_and_cross_run_records(tmp_path):
    fixture, _ = _fixture(tmp_path)
    workspace = tmp_path / "chipstack"
    pipeline = TemporalSlicePipeline(fixture, workspace, simulate_backend=_unavailable)
    first = pipeline.run(seed=10)
    second = pipeline.run(seed=11)
    assert first["workspace"]["run_id"] != second["workspace"]["run_id"]
    assert Path(first["evidence_manifest"]).is_file()
    assert Path(second["evidence_manifest"]).is_file()
    rows = read_workspace_runs(workspace, fixture.name)
    assert len(rows) == 2
    assert {row["seed"] for row in rows} == {10, 11}
    assert {row["manifest_path"] for row in rows} == {
        str(Path(first["evidence_manifest"]).relative_to(workspace)),
        str(Path(second["evidence_manifest"]).relative_to(workspace)),
    }
    latest = json.loads((workspace / "run_manifest.json").read_text(encoding="utf-8"))
    assert latest["latest_run_id"] == second["workspace"]["run_id"]
    with sqlite3.connect(workspace / "artifacts.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_files").fetchone()[0] >= 8
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_legacy_layout_does_not_create_chipstack_or_sqlite(tmp_path):
    fixture, _ = _fixture(tmp_path)
    root = tmp_path / "legacy"
    result = TemporalSlicePipeline(fixture, root, simulate_backend=_unavailable, layout="legacy").run()
    assert "workspace" not in result
    assert Path(result["evidence_manifest"]).is_file()
    assert not (root / "artifacts.sqlite").exists()
    assert not (root / "Archive").exists()
    assert not (root / fixture.name).exists()


def test_design_name_cannot_escape_workspace(tmp_path):
    fixture, _ = _fixture(tmp_path)
    root = tmp_path / "workspace"
    with pytest.raises(ValueError):
        TemporalSlicePipeline(fixture, root, simulate_backend=_unavailable, top_design_name="../escape").run()
    assert not (root.parent / "escape").exists()


def test_malformed_parser_result_preserves_partial_workspace_without_fake_model(tmp_path):
    fixture, _ = _fixture(tmp_path)
    (fixture / "intents/structured.yaml").write_text("interfaces: [\n", encoding="utf-8")
    result = TemporalSlicePipeline(fixture, tmp_path / "workspace").run()
    assert result["overall_status"] == "INCOMPLETE"
    assert not (tmp_path / "workspace" / fixture.name / "mental_model_agent/mental_model.md").exists()
    document = json.loads(Path(result["evidence_manifest"]).read_text(encoding="utf-8"))
    assert document["overall_status"] == "INCOMPLETE"
    assert document["simulation_kind"] == "not_started"
    assert not document["scenarios"]
