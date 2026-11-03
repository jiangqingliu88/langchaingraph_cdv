"""M5：`vagent why` —— 一条义务的取证链（谓词 → 事实 → 状态 → 还差什么）。"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.tools.checking.verification_os import (
    explain, run_shadow, status_summary, write_contract,
)

CASE_IR = {
    "module": "demo",
    "cases": [{
        "id": "CASE-A",
        "groups": [{"group": "CG-A", "cell": "CELL-A-P0",
                    "required_layers": ["functional"], "tp_ids": ["TP-1"]}],
        "sva": [], "scb": [], "not_applicable": {},
    }],
}

CASE_COV = {
    "schema": "case_cov_v1", "case_id": "CASE-A", "tst_id": "TST-A@1",
    "seed": 1, "run_id": "run_x", "task": "t1", "timing_ok": None,
    "scb_summary": {"total": 0, "matched": None, "mismatched": None},
    "tp": [{"tp_id": "TP-1", "coverpoint": "cp_a", "owned": ["b0"],
            "hits": {"b0": 3}, "pct": 100.0, "status": "SIGNED_OFF"}],
    "groups": [{"group": "CG-A", "cell": "CELL-A-P0",
                "functional": {"status": "PROVEN"},
                "timing": {"status": "NOT_APPLICABLE"},
                "data": {"status": "NOT_APPLICABLE"},
                "path": {"status": "NOT_APPLICABLE"}, "result": "PROVEN"}],
    "sva": [], "scb": [], "case_status": "PARTIAL",
}

TESTPOINTS = {"testpoints": [{
    "tp_id": "TP-1", "case_id": "CASE-A", "coverpoint": "cp_a", "bin": "b0",
    "execution": {"test": "demo_env_d_a_p0_test", "stage": "p0",
                  "seeds": [4001, 4002]}}]}


def _run(tmp_path: Path, hits=3) -> Path:
    root = tmp_path / "run_why_20260101_000000"
    (root / "coverage" / "case_cov" / "p0").mkdir(parents=True)
    (root / "coverage" / "case_ir.json").write_text(
        json.dumps(CASE_IR, ensure_ascii=False), encoding="utf-8")
    (root / "coverage" / "testpoints.yaml").write_text(
        yaml.safe_dump(TESTPOINTS, allow_unicode=True), encoding="utf-8")
    rec = json.loads(json.dumps(CASE_COV))
    rec["tp"][0]["hits"]["b0"] = hits
    (root / "coverage" / "case_cov" / "p0" / "t1.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    write_contract(root, CASE_IR)
    run_shadow(root)
    return root


def test_why_shows_predicate_facts_and_status(tmp_path):
    root = _run(tmp_path)
    data = explain(root, "OBL-GROUP-CASE-A-CG-A-FUNCTIONAL")
    assert data["available"] is True
    assert data["status"] == "PROVEN"
    assert data["predicate"]["fact_type"] == "bin_hit"
    assert data["facts_total"] >= 1
    assert "missing" not in data


def test_why_on_missing_evidence_suggests_a_run(tmp_path):
    root = _run(tmp_path, hits=0)
    data = explain(root, "OBL-GROUP-CASE-A-CG-A-FUNCTIONAL")
    assert data["status"] != "PROVEN"
    assert data["missing"]["fact_type"] == "bin_hit"
    runs = data["missing"]["suggested_runs"]
    assert runs and runs[0]["test"] == "demo_env_d_a_p0_test"
    assert runs[0]["seeds"] == [4001, 4002]


def test_why_unknown_obligation_says_so(tmp_path):
    root = _run(tmp_path)
    data = explain(root, "OBL-NOPE")
    assert data["available"] is False
    assert data["reason"] == "obligation_not_found"


def test_why_without_contract_is_honest(tmp_path):
    root = tmp_path / "run_nocontract_20260101_000000"
    root.mkdir()
    data = explain(root, "OBL-X")
    assert data["available"] is False
    assert data["reason"] == "contract_missing"


def test_status_summary_counts_contract_ledger_and_shadows(tmp_path):
    root = _run(tmp_path)
    data = status_summary(root)
    assert data["contract"]["ok"] is True
    assert data["ledger"]["facts"] > 0
    assert data["case_shadow"]["mismatched"] == 0
