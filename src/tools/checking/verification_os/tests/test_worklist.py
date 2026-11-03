"""M4：义务 worklist —— 只重跑"还没清偿"的那几条。

纪律：算不出来就跑全量（`available: false`）；映射不到回归 test 的进
`skipped_no_test`，不静默丢。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.tools.checking.verification_os import (
    build_worklist, regression_test_name, write_contract,
)
from src.tools.checking.verification_os.contract_model import Fact, FactBundle
from src.tools.checking.verification_os.ledger import append_bundle

CASE_IR = {
    "module": "demo",
    "cases": [{
        "id": "CASE-A",
        "groups": [
            {"group": "CG-A", "cell": "CELL-A-P0", "required_layers": ["functional"],
             "tp_ids": ["TP-1"]},
            {"group": "CG-B", "cell": "CELL-B-P1", "required_layers": ["functional"],
             "tp_ids": ["TP-2"]},
        ],
        "sva": [], "scb": [], "not_applicable": {},
    }],
}

TESTPOINTS = {"testpoints": [
    {"tp_id": "TP-1", "case_id": "CASE-A", "coverpoint": "cp_a", "bin": "b0",
     "execution": {"test": "demo_env_d_a_p0_test", "stage": "p0", "seeds": [1]}},
    {"tp_id": "TP-2", "case_id": "CASE-A", "coverpoint": "cp_b", "bin": "b0",
     "execution": {"test": "demo_env_d_b_p1_test", "stage": "p1", "seeds": [7]}},
]}

REGRESSION = {"tests": [{"name": "tp_1"}, {"name": "tp_2"}]}


def _run(tmp_path: Path, *, reg=True, contract=True, fact_tp="TP-1") -> Path:
    root = tmp_path / "run_wl_20260101_000000"
    (root / "coverage").mkdir(parents=True)
    (root / "inputs" / "yaml").mkdir(parents=True)
    (root / "coverage" / "case_ir.json").write_text(
        json.dumps(CASE_IR, ensure_ascii=False), encoding="utf-8")
    (root / "coverage" / "testpoints.yaml").write_text(
        yaml.safe_dump(TESTPOINTS, allow_unicode=True), encoding="utf-8")
    if reg:
        (root / "inputs" / "yaml" / "regression.yaml").write_text(
            yaml.safe_dump(REGRESSION, allow_unicode=True), encoding="utf-8")
    if contract:
        write_contract(root, CASE_IR)
    facts = [Fact(type="bin_hit", contract_hash="",
                  subject={"case": "CASE-A", "tp": fact_tp, "cp": "cp", "bin": "b0"},
                  value={"hits": 3})]
    append_bundle(root, FactBundle(bundle_id="B-1", facts=facts))
    return root


def test_regression_test_name_matches_generator_convention():
    assert regression_test_name("TP-NPUSCH-D_QUEUE-0") == "tp_npusch_d_queue_0"
    assert regression_test_name("tp_x") == "tp_x"


def test_only_unsatisfied_obligation_is_listed(tmp_path):
    root = _run(tmp_path)                    # TP-1 有命中，TP-2 没有
    data = build_worklist(root)
    assert data["available"] is True
    assert data["open"] == 1
    assert data["tests"] == ["tp_2"]
    assert data["items"][0]["seeds"] == [7]
    assert data["items"][0]["obligations"] == [
        "OBL-GROUP-CASE-A-CG-B-FUNCTIONAL"]


def test_the_other_obligation_is_listed_when_only_one_is_hit(tmp_path):
    root = _run(tmp_path, fact_tp="TP-2")    # 只有 TP-2 命中 → 缺的是 TP-1
    assert build_worklist(root)["tests"] == ["tp_1"]


def test_missing_regression_yaml_falls_back_to_full(tmp_path):
    data = build_worklist(_run(tmp_path, reg=False))
    assert data["available"] is False
    assert data["reason"] == "regression_yaml_missing"


def test_missing_contract_falls_back_to_full(tmp_path):
    data = build_worklist(_run(tmp_path, contract=False))
    assert data["available"] is False
    assert data["reason"] == "contract_missing"


def test_tp_without_regression_test_is_reported_not_dropped(tmp_path):
    root = _run(tmp_path)
    (root / "inputs" / "yaml" / "regression.yaml").write_text(
        yaml.safe_dump({"tests": [{"name": "tp_1"}]}, allow_unicode=True),
        encoding="utf-8")
    data = build_worklist(root)
    assert data["tests"] == []          # 缺的那条没有对应回归 test → 不编一个
    assert any(s["reason"] == "no_regression_test"
               for s in data["skipped_no_test"])
