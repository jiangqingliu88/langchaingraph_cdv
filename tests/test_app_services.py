from __future__ import annotations

import json

import pytest

from src.workbench.api import (
    analyze_plan, list_ips, run_closure, run_soc_project,
)
from src.orchestration_plane.l2.regression_tools.backend_capabilities import (
    capabilities, supports,
)
from src.workbench.query.evidence import read_envelope, validate_evidence
from src.workbench.query.runs import read_events


def _run(tmp_path):
    root = tmp_path / "output_demo"
    (root / "regression_run" / "p0").mkdir(parents=True)
    (root / "coverage").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "regression_run" / "p0" / "report.json").write_text(json.dumps({
        "total_time": "00:00:10", "total": 1,
        "stats": {"pass": 1, "fail": 0, "unknown": 0},
        "tasks": [{"name": "test_a", "status": "pass", "elapsed": 10.0}],
    }), encoding="utf-8")
    (root / "coverage" / "tp_matrix.json").write_text(
        json.dumps({"rows": [], "counts": {}}), encoding="utf-8")
    (root / "docs" / "events.jsonl").write_text(
        json.dumps({"event_type": "run.started", "seq": 1}) + "\n",
        encoding="utf-8")
    return root


def test_optimize_service_builds_plan(tmp_path):
    root = _run(tmp_path)
    payload = analyze_plan(project=tmp_path, output=root)
    assert payload["plan"]["tests"] == 1
    assert payload["result"] is None
    assert (root / "optimize" / "plan.json").is_file()


def test_coverage_service_writes_plan(tmp_path):
    root = _run(tmp_path)
    (root / "sim" / "coverage").mkdir(parents=True)
    (root / "sim" / "coverage" / "coverage_result.json").write_text(
        json.dumps({"functional_pct": 90.0}), encoding="utf-8")
    (root / "coverage" / "tp_matrix.json").write_text(json.dumps({
        "rows": [{"tp_id": "TP-A", "coverpoint": "cp", "bin": "b1",
                  "status": "MISS"}]}), encoding="utf-8")
    payload = run_closure(project=tmp_path, coverage=root, target=98.0,
                          execute=False)
    assert payload["plan"]["gap_count"] == 1
    assert (root / "closure" / "plan.json").is_file()


def test_query_layer_reads_events(tmp_path):
    root = _run(tmp_path)
    assert read_events(root, "run.started")[0]["seq"] == 1


def test_query_evidence_handles_old_package(tmp_path):
    pkg = tmp_path / "signoff_evidence"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(
        json.dumps({"schema": "old_pkg", "files": []}), encoding="utf-8")
    assert read_envelope(pkg) == {}
    assert validate_evidence(pkg)[0]["code"] == "missing_envelope"


def test_backend_capabilities_are_explicit():
    assert capabilities("questa")["coverage"] is True
    assert capabilities("verilator")["sim"] is False
    ok, why = supports("verilator", "coverage")
    assert ok is False and "未实现" in why


def test_services_are_importable():
    assert callable(run_soc_project)
    assert callable(list_ips)
