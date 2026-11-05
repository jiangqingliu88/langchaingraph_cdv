from __future__ import annotations

import json

from src.core.provenance.attribution import classify
from src.core.provenance.graph import build_provenance, write_provenance
from src.core.provenance.report import build_attribution_report


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _run(tmp_path):
    _write(tmp_path / "coverage" / "testpoints.json", {"testpoints": [
        {"tp_id": "TP-A", "coverpoint": "cp", "bin": "b1"},
        {"tp_id": "TP-B", "coverpoint": "cp", "bin": "b2"},
        {"tp_id": "TP-C", "coverpoint": "cp", "bin": "b3"},
    ]})
    _write(tmp_path / "coverage" / "tp_matrix.json", {"rows": [
        {"tp_id": "TP-A", "coverpoint": "cp", "bin": "b1", "status": "HIT"},
        {"tp_id": "TP-B", "coverpoint": "cp", "bin": "b2", "status": "MISS"},
        {"tp_id": "TP-C", "coverpoint": "cp", "bin": "b3", "status": "UNMAPPED"},
    ]})
    _write(tmp_path / "coverage" / "round_manifest.json", {"rounds": [
        {"round": 1, "facts": [{"tp_id": "TP-A", "test_name": "alu_test"}]},
    ]})
    test_dir = tmp_path / "regression_run" / "p0" / "build_x" / "test_alu_test_seed_7"
    test_dir.mkdir(parents=True)
    (test_dir / "sim_vsim.log").write_text("mismatched=0\n", encoding="utf-8")
    _write(tmp_path / "coverage" / "stimulus_plan.json",
           {"sha256": "abc123", "testpoints": []})
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
    return tmp_path


def test_seed_is_read_from_directory_name(tmp_path):
    attr = classify(_run(tmp_path))
    assert attr.tests["alu_test"]["seeds"] == {7}


def test_without_per_test_data_bin_to_test_is_weak(tmp_path):
    root = _run(tmp_path)
    attr = classify(root)
    assert attr.bin_tests_weak["bin:cp.b1"] == {"alu_test"}
    assert attr.bin_tests_exact == {}
    graph = build_provenance(root)
    assert graph.has_edge("bin:cp.b1", "test:alu_test", "attributed_by")
    assert not graph.has_edge("bin:cp.b1", "test:alu_test", "hit_by")


def test_miss_and_unmapped_bins_get_no_hit_edge(tmp_path):
    graph = build_provenance(_run(tmp_path))
    assert not graph.has_edge("bin:cp.b2", "test:alu_test", "attributed_by")
    assert not graph.has_edge("bin:cp.b3", "test:alu_test", "attributed_by")


def test_per_test_sidecar_makes_attribution_exact(tmp_path):
    root = _run(tmp_path)
    _write(root / "coverage" / "per_test_bins.json",
           {"schema": "per_test_bins_v1", "tests": {"alu_test": ["cp.b1"]}})
    attr = classify(root)
    assert attr.bin_tests_exact["bin:cp.b1"] == {"alu_test"}
    graph = build_provenance(root)
    assert graph.has_edge("bin:cp.b1", "test:alu_test", "hit_by")


def test_tp_and_derivation_edges_are_present(tmp_path):
    graph = build_provenance(_run(tmp_path))
    assert graph.has_edge("tp:TP-A", "bin:cp.b1", "aggregates")
    assert graph.has_edge("test:alu_test", "tp:TP-A", "realizes")
    assert graph.has_edge("test:alu_test", "seed:7", "seed_derived")


def test_build_is_deterministic(tmp_path):
    root = _run(tmp_path)
    a = build_provenance(root).to_jsonl()
    b = build_provenance(root).to_jsonl()
    assert a == b


def test_write_provenance_and_summary(tmp_path):
    root = _run(tmp_path)
    out = write_provenance(root)
    assert out["jsonl_sha256"]
    assert (root / "docs" / "provenance.jsonl").is_file()
    summary = json.loads(
        (root / "docs" / "provenance_summary.json").read_text(encoding="utf-8"))
    assert summary["nodes"] > 0
    assert summary["by_confidence"]["weak"] == 1
    assert summary["notes"]


def test_execution_chain_reaches_plan_and_rtl(tmp_path):
    graph = build_provenance(_run(tmp_path))
    assert graph.has_edge("test:alu_test", "artifact:stimulus_plan:coverage/stimulus_plan.json",
                          "executed_with")
    assert graph.has_edge("test:alu_test", "artifact:rtl_dir", "executed_against")
    assert graph.has_node("artifact:rtl_dir")


def test_attribution_report_counts_complete_chain(tmp_path):
    root = _run(tmp_path)
    report = build_attribution_report(root)
    assert report["hit_bins"] == 1
    assert report["with_tp"] == 1
    assert report["with_test"] == 1
    assert report["with_seed"] == 1
    assert report["with_stimulus_plan"] == 1
    assert report["with_rtl"] == 1
    assert report["complete_chain"] == 1
    assert report["attribution_rate"] == 1.0
    assert report["test_seed_rate"] == 1.0
    assert report["weak_rate"] == 1.0
    assert report["exact_rate"] == 0.0


def test_attribution_report_exact_with_sidecar(tmp_path):
    root = _run(tmp_path)
    _write(root / "coverage" / "per_test_bins.json",
           {"tests": {"alu_test": ["cp.b1"]}})
    report = build_attribution_report(root)
    assert report["exact_rate"] == 1.0
    assert report["weak_rate"] == 0.0


def test_attribution_report_breaks_when_plan_or_rtl_missing(tmp_path):
    root = _run(tmp_path)
    (root / "coverage" / "stimulus_plan.json").unlink()
    (root / "rtl" / "dut.sv").unlink()
    report = build_attribution_report(root)
    assert report["with_stimulus_plan"] == 0
    assert report["with_rtl"] == 0
    assert report["complete_chain"] == 0
    assert report["attribution_rate"] == 0.0
