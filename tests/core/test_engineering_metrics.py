from __future__ import annotations

import json

from src.runtime_plane.core.decision.eval import append_record, evaluate_round
from src.runtime_plane.core.metrics.engineering import collect, write


def _w(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _run(tmp_path, name="run", seconds="00:00:20", functional=90.0):
    root = tmp_path / name
    _w(root / "regression_run" / "p0" / "report.json", {
        "total_time": seconds, "total": 2,
        "stats": {"pass": 2, "fail": 0, "unknown": 0},
        "tasks": [{"name": "test_a", "status": "pass", "elapsed": 8.0},
                  {"name": "test_b", "status": "pass", "elapsed": 12.0}],
    })
    _w(root / "sim" / "coverage" / "coverage_result.json",
       {"functional_pct": functional, "overall_pct": 80.0})
    _w(root / "coverage" / "tp_matrix.json", {"total": 2, "counts": {"HIT": 1, "MISS": 1}})
    _w(root / "coverage" / "testpoints.json", {"testpoints": [
        {"tp_id": "TP-A", "coverpoint": "cp", "bin": "b1"}]})
    _w(root / "coverage" / "tp_matrix.json", {"rows": [
        {"tp_id": "TP-A", "coverpoint": "cp", "bin": "b1", "status": "HIT"}],
        "total": 1, "counts": {"HIT": 1}})
    _w(root / "coverage" / "round_manifest.json", {"rounds": [
        {"round": 1, "facts": [{"tp_id": "TP-A", "test_name": "a"}]}]})
    _w(root / "coverage" / "per_test_bins.json", {"tests": {"a": ["cp.b1"]}})
    _w(root / "coverage" / "stimulus_plan.json", {"sha256": "plan"})
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
    test_dir = root / "regression_run" / "p0" / "test_a_seed_1"
    test_dir.mkdir(parents=True)
    (test_dir / "sim_vsim.log").write_text("mismatched=0\n", encoding="utf-8")
    return root


def _decision(root, round_num, status):
    rec = evaluate_round(
        run_id=root.name, round_num=round_num,
        action={"action_type": "GENERATE_DIRECTED_TEST"},
        expected={}, actual=status)
    append_record(root, rec)


def test_collects_regression_attribution_and_decision(tmp_path):
    root = _run(tmp_path)
    _decision(root, 1, {"prev_coverage": 80.0, "coverage": 85.0, "new_hits": 1,
                        "tests_failed": 0, "tests_failed_prev": 0,
                        "compile_ok": True, "compile_ok_prev": True,
                        "tp_matrix_available": True})
    _decision(root, 2, {"prev_coverage": 85.0, "coverage": 85.0, "new_hits": 0,
                        "tests_failed": 0, "tests_failed_prev": 0,
                        "compile_ok": True, "compile_ok_prev": True,
                        "tp_matrix_available": True})
    out = collect(root)
    assert out["regression"]["total_seconds"] == 20.0
    assert out["attribution"]["hit_bins"] == 1
    assert out["attribution"]["attribution_rate"] == 1.0
    assert out["decision"]["evaluated"] == 2
    assert out["decision"]["effective"] == 1
    assert out["decision"]["ineffective"] == 1
    assert out["decision"]["effectiveness_rate"] == 0.5


def test_missing_data_is_null_not_zero(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    out = collect(empty)
    assert out["regression"]["total_seconds"] is None
    assert out["decision"]["effectiveness_rate"] is None
    assert out["incremental"]["available"] is False


def test_baseline_comparison_reports_regression_reduction(tmp_path):
    base = _run(tmp_path, "base", "00:00:40")
    cur = _run(tmp_path, "cur", "00:00:20")
    out = collect(cur, baseline=base)
    assert out["baseline"]["regression_total_seconds"] == 40.0
    assert out["baseline"]["regression_reduction_pct"] == 50.0


def test_write_metrics_file_and_event(tmp_path):
    from src.runtime_plane.core.runtime.events import EventStore
    root = _run(tmp_path)
    events = EventStore(root, run_id=root.name)
    out = write(root, event_store=events)
    assert (root / "docs" / "engineering_metrics.json").is_file()
    assert events.read("metrics.collected")
