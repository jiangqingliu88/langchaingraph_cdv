from __future__ import annotations

import json

from src.runtime_plane.core.closure.plan import build_closure_plan, write_closure_plan


def _w(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _run(tmp_path):
    _w(tmp_path / "sim" / "coverage" / "coverage_result.json",
       {"functional_pct": 90.0, "overall_pct": 80.0})
    _w(tmp_path / "coverage" / "tp_matrix.json", {"rows": [
        {"tp_id": "TP-A", "coverpoint": "cp", "bin": "b1", "status": "MISS",
         "requirement": "MUST work"},
        {"tp_id": "TP-B", "coverpoint": "cp", "bin": "b2", "status": "HIT"},
        {"tp_id": "TP-C", "coverpoint": "cp", "bin": "b3", "status": "UNMAPPED"},
    ]})
    return tmp_path


def test_closure_plan_lists_gaps_and_actions(tmp_path):
    plan = build_closure_plan(_run(tmp_path), 98.0)
    assert plan["current_coverage"] == 90.0
    assert plan["target"] == 98.0
    assert plan["gap_to_target"] == 8.0
    assert plan["gap_count"] == 2
    actions = {a["tp_id"]: a for a in plan["actions"]}
    assert actions["TP-A"]["action"] == "GENERATE_DIRECTED_TEST"
    assert actions["TP-A"]["priority"] == "HIGH"
    assert actions["TP-C"]["action"] == "AUDIT_COVERPOINT"


def test_closure_plan_is_written(tmp_path):
    root = _run(tmp_path)
    plan = write_closure_plan(root, 98.0)
    assert (root / "closure" / "plan.json").is_file()
    assert plan["path"].endswith("plan.json")


def test_no_rows_is_explicit_not_silent(tmp_path):
    plan = build_closure_plan(tmp_path, 98.0)
    assert plan["gap_count"] == 0
    assert plan["notes"]
