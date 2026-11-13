"""轮次事实表 —— 第几轮、哪条用例、哪个后端、哪份 plan、播放日志哈希。"""
from __future__ import annotations

import json
from pathlib import Path

from src.orchestration_plane.l2.evidence.round_facts import (
    build_round_facts,
    load_round_manifest,
    record_round_facts,
    validate_round_manifest,
)


def _run(tmp_path, plan_sha="plan-sha"):
    root = tmp_path / "run"
    (root / "coverage").mkdir(parents=True)
    (root / "regression_run" / "p0" / "t_a").mkdir(parents=True)
    (root / "regression_run" / "p0" / "t_a" / "sim_vsim.log").write_text(
        "UVM_ERROR : 0\nmismatched=0\n", encoding="utf-8")
    (root / "coverage" / "testpoints.json").write_text(json.dumps({
        "testpoints": [
            {"tp_id": "TP1", "dimension": "D1",
             "realization": {"kind": "stimulus"},
             "execution": {"test": "t_a", "stage": "p0"},
             "status_rule": {"pass": "UVM_ERROR=0", "evidence": "bin b1"}},
            {"tp_id": "TP2", "dimension": "D2",
             "realization": {"kind": "observe"},
             "execution": {"test": "t_o", "stage": "p1"}},
        ]
    }), encoding="utf-8")
    (root / "coverage" / "stimulus_plan.json").write_text(json.dumps({
        "schema": "stimulus_plan_v1", "backend": "generated", "sha256": plan_sha,
        "testpoints": [{"tp_id": "TP1", "kind": "stimulus", "test": "t_a",
                        "transactions": [{"field": "f", "value": 0}]}],
        "unsupported": [{"tp_id": "TP2", "kind": "observe"}],
    }), encoding="utf-8")
    (root / "coverage" / "tp_matrix.json").write_text(json.dumps({
        "rows": [{"tp_id": "TP1", "status": "HIT"},
                 {"tp_id": "TP2", "status": "OBSERVED"}]
    }), encoding="utf-8")
    return root


def test_build_facts_has_per_test_plan_and_log(tmp_path):
    facts = build_round_facts(_run(tmp_path), 1)
    assert [f["tp_id"] for f in facts] == ["TP1", "TP2"]
    a = facts[0]
    assert a["backend"] == "generated"
    assert a["plan_sha256"] == "plan-sha" and a["entry_sha256"]
    assert a["playback_log_sha256"] and len(a["playback_log_sha256"]) == 64
    assert "UVM_ERROR=0" in a["pass_criteria"]
    assert a["status"] == "HIT"
    # 不在 plan 的 observe：如实 backend 空、plan 空
    assert facts[1]["plan_sha256"] == "" and facts[1]["backend"] == ""


def test_record_replaces_round_and_is_stable(tmp_path):
    root = _run(tmp_path)
    first = record_round_facts(root, 1)
    second = record_round_facts(root, 1)
    doc = load_round_manifest(root)
    assert first["sha256"] == second["sha256"]
    assert len(doc["rounds"]) == 1
    assert doc["query_contract"] == "round_facts_v1"
    record_round_facts(root, 2)
    assert [r["round"] for r in load_round_manifest(root)["rounds"]] == [1, 2]


def test_round_zero_is_a_noop(tmp_path):
    root = _run(tmp_path)
    assert record_round_facts(root, 0) == {}
    assert not (root / "coverage" / "round_manifest.json").exists()


def test_plan_drift_is_detected(tmp_path):
    root = _run(tmp_path)
    record_round_facts(root, 1)
    (root / "coverage" / "stimulus_plan.json").write_text(json.dumps({
        "schema": "stimulus_plan_v1", "backend": "generated",
        "sha256": "changed", "testpoints": [], "unsupported": [],
    }), encoding="utf-8")
    issues = validate_round_manifest(root)
    assert any(i["type"] == "plan_drift" for i in issues)
