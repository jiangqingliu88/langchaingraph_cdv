from __future__ import annotations

import json

from src.core.incremental.dependencies import affected_tests, load_dependency_map
from src.core.incremental.plan import build_plan, write_plan
from src.core.incremental.rtl_diff import diff_runs
from src.core.incremental.run_diff import compare_runs


def _w(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _run(tmp_path, name, alu, report=None):
    root = tmp_path / name
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "alu.sv").write_text(alu, encoding="utf-8")
    (root / "rtl" / "apb.sv").write_text("module apb; endmodule\n", encoding="utf-8")
    _w(root / "coverage" / "test_dependencies.json", {
        "tests": {"alu_test": {"files": ["rtl/alu.sv"]},
                  "apb_test": {"files": ["rtl/apb.sv"]}}})
    _w(root / "coverage" / "round_manifest.json", {"rounds": [
        {"round": 1, "facts": [
            {"tp_id": "TP-A", "test_name": "alu_test"},
            {"tp_id": "TP-B", "test_name": "apb_test"},
        ]}]})
    _w(root / "coverage" / "tp_matrix.json", {"total": 3, "counts": {"HIT": 2, "MISS": 1}})
    if report is not None:
        _w(root / "regression_run" / "p0" / "report.json", report)
    return root


def _report():
    return {
        "total_time": "00:00:30", "total": 2,
        "stats": {"pass": 2, "fail": 0, "unknown": 0},
        "tasks": [{"name": "test_alu_test", "status": "pass", "elapsed": 10.0},
                  {"name": "test_apb_test", "status": "pass", "elapsed": 20.0}],
    }


def test_rtl_diff_uses_content_not_mtime(tmp_path):
    base = _run(tmp_path, "base", "module alu; endmodule\n", _report())
    cur = _run(tmp_path, "cur", "module alu; wire x; endmodule\n", _report())
    diff = diff_runs(base, cur)
    assert diff["modified"] == ["alu.sv"]
    assert diff["unchanged"] == 1


def test_dependency_map_and_affected_tests(tmp_path):
    root = _run(tmp_path, "r", "x", _report())
    dep = load_dependency_map(root)
    out = affected_tests(["rtl/alu.sv"], dep, ["alu_test", "apb_test"])
    assert out["selected"] == ["alu_test"]
    assert out["excluded"] == ["apb_test"]
    assert out["confidence"] == "mapped"


def test_undeclared_test_is_conservative(tmp_path):
    root = _run(tmp_path, "r", "x", _report())
    dep = load_dependency_map(root)
    out = affected_tests(["rtl/alu.sv"], dep, ["alu_test", "ghost_test"])
    assert "ghost_test" in out["selected"]
    assert out["undeclared"] == ["ghost_test"]


def test_no_dependency_map_means_conservative_all():
    out = affected_tests(["rtl/alu.sv"], {}, ["a", "b"])
    assert out["selected"] == ["a", "b"]
    assert out["confidence"] == "conservative_all"


def test_plan_estimates_savings_from_baseline_elapsed(tmp_path):
    base = _run(tmp_path, "base", "module alu; endmodule\n", _report())
    cur = _run(tmp_path, "cur", "module alu; wire x; endmodule\n", _report())
    plan = build_plan(base, cur)
    assert plan["selected_tests"] == ["alu_test"]
    assert plan["all_tests"] == 2
    assert plan["estimated_full_seconds"] == 30.0
    assert plan["estimated_selected_seconds"] == 10.0
    assert plan["estimated_savings_seconds"] == 20.0
    assert plan["estimated_savings_pct"] == 66.67
    assert plan["confidence"] == "mapped"


def test_write_plan_lands_in_current_run(tmp_path):
    base = _run(tmp_path, "base", "a", _report())
    cur = _run(tmp_path, "cur", "b", _report())
    out = write_plan(base, cur)
    assert (cur / "incremental" / "plan.json").is_file()
    assert out["path"].endswith("plan.json")


def test_run_diff_has_rtl_and_metric_deltas(tmp_path):
    base = _run(tmp_path, "base", "module alu; endmodule\n", _report())
    cur = _run(tmp_path, "cur", "module alu; wire x; endmodule\n", _report())
    diff = compare_runs(base, cur)
    assert diff["rtl"]["modified"] == ["alu.sv"]
    assert "decision_rate" in diff["deltas"]
    assert "attribution_rate" in diff["deltas"]
