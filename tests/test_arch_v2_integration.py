"""Architecture 2.0 合成 run 的集成测试 —— 不跑 EDA、不调 LLM。"""
from __future__ import annotations

import json
from pathlib import Path

from src.core.decision.eval import append_record, evaluate_round
from src.core.provenance.graph import write_provenance
from src.core.runtime.events import EventStore
from src.core.verification.quality import write as write_quality
from src.layers.l2_orchestration.evidence.signoff_package import (
    verify_package, write_package,
)


def _w(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _run(tmp_path: Path) -> Path:
    root = tmp_path / "output_demo_20261031_120000"
    _w(root / "coverage" / "testpoints.json", {"testpoints": [
        {"tp_id": "TP-A", "coverpoint": "cp", "bin": "b1"},
    ]})
    _w(root / "coverage" / "tp_matrix.json", {"rows": [
        {"tp_id": "TP-A", "coverpoint": "cp", "bin": "b1", "status": "HIT"},
    ], "counts": {"HIT": 1}})
    _w(root / "coverage" / "round_manifest.json", {"rounds": [
        {"round": 1, "facts": [{"tp_id": "TP-A", "test_name": "alu_test"}]},
    ]})
    _w(root / "coverage" / "per_test_bins.json",
       {"schema": "per_test_bins_v1", "tests": {"alu_test": ["cp.b1"]}})
    test_dir = root / "regression_run" / "p0" / "build_x" / "test_alu_test_seed_7"
    test_dir.mkdir(parents=True)
    (test_dir / "sim_vsim.log").write_text("mismatched=0\n", encoding="utf-8")

    _w(root / "regression_stages.json",
       {"status": "PASS", "passed": 10, "failed": 0, "total": 10})
    _w(root / "sim" / "coverage" / "coverage_result.json",
       {"functional_pct": 96.0, "overall_pct": 80.0})
    (root / "inputs" / "yaml" / "uvm").mkdir(parents=True, exist_ok=True)
    (root / "inputs" / "yaml" / "uvm" / "models.yaml").write_text(
        "models:\n  - name: m\n    status: verified\n", encoding="utf-8")
    _w(root / "docs" / "file_change_chain.json", {"chain_valid": True})
    (root / "docs" / "tool_receipts.jsonl").write_text("{}\n", encoding="utf-8")
    return root


def test_provenance_quality_decision_and_package_together(tmp_path):
    root = _run(tmp_path)
    events = EventStore(root, run_id=root.name)

    prov = write_provenance(root, event_store=events)
    quality = write_quality(root, target=95.0, event_store=events)
    record = evaluate_round(
        run_id=root.name, round_num=1,
        action={"action_type": "GENERATE_DIRECTED_TEST", "reason": "gap",
                "source": "rule"},
        expected={"round": 1, "needs_human": False},
        actual={"prev_coverage": 90.0, "coverage": 92.0, "new_hits": 1,
                "lost_hits": 0, "tests_failed": 0, "tests_failed_prev": 0,
                "compile_ok": True, "compile_ok_prev": True,
                "tp_matrix_available": True})
    assert append_record(root, record) is True

    assert prov["summary"]["nodes"] > 0
    assert quality["overall"] in ("pass", "warn")
    assert events.read("provenance.built")
    assert events.read("quality.gate")

    manifest = write_package(root, {
        "run": root.name, "verdict": {"verdict": "READY"},
        "artifacts": {}, "tp_matrix": {"counts": {"HIT": 1}},
    }, project_root=tmp_path)
    rels = {f["path"] for f in manifest["files"]}
    assert "execution/docs/provenance.jsonl" in rels
    assert "execution/docs/provenance_summary.json" in rels
    assert "execution/docs/events.jsonl" in rels
    assert "execution/decision/evaluations.jsonl" in rels
    assert "verdict/docs/verification_quality.json" in rels

    check = verify_package(root / "signoff_evidence")
    assert check["ok"], check
