from __future__ import annotations

import json

from src.runtime_plane.core.verification.quality import DIMENSIONS, evaluate, write


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_all_dimensions_unknown_without_evidence(tmp_path):
    report = evaluate(tmp_path)
    assert set(report["dimensions"]) == set(DIMENSIONS)
    assert all(d["status"] in ("unknown", "not_applicable")
               for d in report["dimensions"].values())
    assert report["overall"] == "unknown"


def test_unknown_is_never_coerced_to_pass(tmp_path):
    report = evaluate(tmp_path)
    assert report["dimensions"]["functional"]["status"] != "pass"


def _good_run(tmp_path):
    _write(tmp_path / "regression_stages.json",
           {"status": "PASS", "passed": 10, "failed": 0, "total": 10})
    _write(tmp_path / "sim" / "coverage" / "coverage_result.json",
           {"functional_pct": 96.0, "overall_pct": 80.0})
    _write(tmp_path / "coverage" / "tp_matrix.json",
           {"counts": {"HIT": 8, "UNMAPPED": 0}})
    (tmp_path / "inputs" / "yaml" / "uvm").mkdir(parents=True, exist_ok=True)
    (tmp_path / "inputs" / "yaml" / "uvm" / "models.yaml").write_text(
        "models:\n  - name: m\n    status: verified\n", encoding="utf-8")
    _write(tmp_path / "coverage" / "round_manifest.json",
           {"rounds": [{"round": 1, "facts": []}]})
    _write(tmp_path / "docs" / "file_change_chain.json", {"chain_valid": True})
    _write(tmp_path / "docs" / "provenance_summary.json", {"by_confidence": {"exact": 3}})
    (tmp_path / "docs" / "provenance.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "docs" / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "docs" / "tool_receipts.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "coverage" / "per_test_bins.json").write_text("{}", encoding="utf-8")


def test_good_run_passes_all_dimensions(tmp_path):
    _good_run(tmp_path)
    report = evaluate(tmp_path, target=95.0)
    assert report["dimensions"]["functional"]["status"] == "pass"
    assert report["dimensions"]["coverage"]["status"] == "pass"
    assert report["dimensions"]["model"]["status"] == "pass"
    assert report["dimensions"]["structural"]["status"] == "pass"
    assert report["dimensions"]["evidence"]["status"] == "pass"
    assert report["overall"] == "pass"


def test_placeholder_model_is_warn(tmp_path):
    _good_run(tmp_path)
    (tmp_path / "inputs" / "yaml" / "uvm" / "models.yaml").write_text(
        "placeholder: true\n", encoding="utf-8")
    report = evaluate(tmp_path, target=95.0)
    assert report["dimensions"]["model"]["status"] == "warn"
    assert report["overall"] == "warn"


def test_regression_failure_is_fail(tmp_path):
    _good_run(tmp_path)
    _write(tmp_path / "regression_stages.json",
           {"status": "FAIL", "passed": 9, "failed": 1, "total": 10})
    report = evaluate(tmp_path, target=95.0)
    assert report["dimensions"]["functional"]["status"] == "fail"
    assert report["overall"] == "fail"


def test_write_creates_file_and_event(tmp_path):
    _good_run(tmp_path)
    from src.runtime_plane.core.runtime.events import EventStore
    events = EventStore(tmp_path, run_id="r1")
    report = write(tmp_path, target=95.0, event_store=events)
    assert (tmp_path / "docs" / "verification_quality.json").is_file()
    assert events.read("quality.gate")[0]["status"] == report["overall"]
