from __future__ import annotations

import json

from src.runtime_plane.core.optimize.history import collect_history, find_run_dirs
from src.runtime_plane.core.optimize.plan import build_plan
from src.runtime_plane.core.optimize.result import compare_reports


def _w(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _run(tmp_path, name, tasks, bins=None):
    root = tmp_path / name
    _w(root / "regression_run" / "p0" / "report.json", {
        "total_time": "00:00:30", "total": len(tasks),
        "stats": {"pass": sum(1 for t in tasks if t["status"] == "pass"),
                  "fail": sum(1 for t in tasks if t["status"] == "fail"),
                  "unknown": 0},
        "tasks": tasks,
    })
    if bins:
        _w(root / "coverage" / "attribution.json", {"bins": bins})
    return root


def test_history_collects_status_seed_and_elapsed(tmp_path):
    root = _run(tmp_path, "output_r1", [
        {"name": "test_alu_test_seed_1", "status": "pass", "elapsed": 10.0},
        {"name": "test_apb_test", "status": "fail", "elapsed": 20.0},
    ])
    report = collect_history(find_run_dirs(tmp_path))
    assert report["tests"]["alu_test"]["pass"] == 1
    assert report["tests"]["alu_test"]["seeds"] == ["1"]
    assert report["tests"]["apb_test"]["fail"] == 1
    assert report["summary"]["avg_total_seconds"] == 30.0


def test_flaky_and_failing_are_classified(tmp_path):
    _run(tmp_path, "output_r1", [
        {"name": "test_a", "status": "pass", "elapsed": 1.0},
        {"name": "test_b", "status": "fail", "elapsed": 1.0},
    ])
    _run(tmp_path, "output_r2", [
        {"name": "test_a", "status": "fail", "elapsed": 1.0},
        {"name": "test_b", "status": "fail", "elapsed": 1.0},
    ])
    plan = build_plan(collect_history(find_run_dirs(tmp_path)))
    assert "a" in plan["flaky"]
    assert "b" in plan["failing"]
    assert plan["skipped_tests"] == []
    assert plan["confidence"] == "analysis_only"


def test_low_marginal_only_with_exact_subset_bins(tmp_path):
    bins = [
        {"bin": "cp.x", "tests": ["a"], "confidence": "exact"},
        {"bin": "cp.x", "tests": ["b"], "confidence": "exact"},
        {"bin": "cp.y", "tests": ["b"], "confidence": "exact"},
    ]
    _run(tmp_path, "output_r1", [
        {"name": "test_a", "status": "pass", "elapsed": 10.0},
        {"name": "test_b", "status": "pass", "elapsed": 20.0},
    ], bins)
    plan = build_plan(collect_history(find_run_dirs(tmp_path)))
    assert plan["skipped_tests"] == ["a"]       # a 的 bin 被 b 完全覆盖
    assert plan["selected_tests"] == ["b"]
    assert plan["confidence"] == "exact"
    assert plan["estimated_savings_seconds"] == 10.0


def test_weak_attribution_never_skips(tmp_path):
    bins = [
        {"bin": "cp.x", "tests": ["a", "b"], "confidence": "weak"},
    ]
    _run(tmp_path, "output_r1", [
        {"name": "test_a", "status": "pass", "elapsed": 10.0},
        {"name": "test_b", "status": "pass", "elapsed": 20.0},
    ], bins)
    plan = build_plan(collect_history(find_run_dirs(tmp_path)))
    assert plan["skipped_tests"] == []
    assert plan["confidence"] == "analysis_only"


def test_compare_reports_reports_status_and_time_delta():
    before = {"tasks": [
        {"name": "test_a", "status": "pass", "elapsed": 10.0},
        {"name": "test_b", "status": "pass", "elapsed": 20.0},
    ]}
    after = {"tasks": [{"name": "test_b", "status": "pass", "elapsed": 20.0}]}
    out = compare_reports(before, after)
    assert out["removed_tests"] == ["a"]
    assert out["elapsed_seconds"]["saved"] == 10.0
    assert out["status_changes"] == {}
