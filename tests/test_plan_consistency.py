"""TP IR / StimulusPlan / constraint_backing 三份真相的一致性。"""
from __future__ import annotations

import json

import yaml

from src.ir_plane.vplan.runtime.framework.plan_consistency import (
    build_plan_consistency,
    write_plan_consistency,
)


def _write_run(tmp_path, tps, plan_entries, policies, unsupported=None):
    cov = tmp_path / "coverage"
    cov.mkdir(parents=True)
    (cov / "testpoints.json").write_text(json.dumps(
        {"testpoints": tps}, ensure_ascii=False), encoding="utf-8")
    (cov / "stimulus_plan.json").write_text(json.dumps({
        "schema": "stimulus_plan_v1", "backend": "generated",
        "sha256": "plan-sha", "testpoints": plan_entries,
        "unsupported": unsupported or [],
    }, ensure_ascii=False), encoding="utf-8")
    (cov / "coverage_plan.yaml").write_text(yaml.safe_dump({
        "constraint_backing": {"policies": policies},
    }, allow_unicode=True), encoding="utf-8")
    return tmp_path


def _tp(tp_id, dim, kind="stimulus"):
    return {"tp_id": tp_id, "dimension": dim,
            "realization": {"kind": kind, "field": "f", "value": 0}}


def _entry(tp_id, kind="stimulus", field="f"):
    return {"tp_id": tp_id, "kind": kind,
            "transactions": [{"field": field, "value": 0}]}


def test_consistent_plan_has_no_issues(tmp_path):
    _write_run(
        tmp_path, [_tp("TP1", "D1")], [_entry("TP1")],
        [{"name": "p1", "backed": True, "dimensions": ["D1"]}])
    report = build_plan_consistency(tmp_path)
    assert report["issues"] == []
    assert report["unconstrained"] == []
    assert report["counts"]["planned"] == 1


def test_kind_mismatch_and_missing_tp_are_issues(tmp_path):
    _write_run(
        tmp_path,
        [_tp("TP1", "D1", "sequence")],
        [_entry("TP1", kind="stimulus"), _entry("TP-X")],
        [{"name": "p1", "backed": True, "dimensions": ["D1"]}])
    types = {i["type"] for i in build_plan_consistency(tmp_path)["issues"]}
    assert {"kind_mismatch", "tp_missing"} <= types


def test_dangling_constraint_is_an_issue(tmp_path):
    _write_run(
        tmp_path, [_tp("TP1", "D1")], [_entry("TP1")],
        [{"name": "p_unused", "backed": True, "dimensions": ["D9"]}])
    report = build_plan_consistency(tmp_path)
    assert any(i["type"] == "dangling_constraint" for i in report["issues"])


def test_unbacked_dimension_is_explicitly_unconstrained_not_an_issue(tmp_path):
    _write_run(tmp_path, [_tp("TP1", "D1")], [_entry("TP1")], [])
    report = build_plan_consistency(tmp_path)
    assert report["issues"] == []
    assert report["unconstrained"][0]["dimension"] == "D1"


def test_write_plan_consistency(tmp_path):
    _write_run(
        tmp_path, [_tp("TP1", "D1")], [_entry("TP1")],
        [{"name": "p1", "backed": True, "dimensions": ["D1"]}])
    summary = write_plan_consistency(tmp_path)
    assert summary["ok"] is True
    path = tmp_path / "coverage" / "plan_consistency.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == "plan_consistency_v1"
    assert len(summary["sha256"]) == 64


def test_verify_runs_consistency_after_testpoints_are_written():
    """回归：早于 TP IR 落盘时 counts 全是 0，只剩一堆假 dangling。"""
    from pathlib import Path

    src = Path("src/generation_plane/verification/main.py").read_text(encoding="utf-8")
    assert src.index("self._write_testpoints(") < src.index(
        "self._write_plan_consistency(")
