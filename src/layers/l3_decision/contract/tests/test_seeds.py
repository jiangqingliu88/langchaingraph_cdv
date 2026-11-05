"""P6：种子索引 —— 哪颗 seed 清偿了哪些义务（可复现证据）。"""
from __future__ import annotations

import json
from pathlib import Path

from src.layers.l3_decision.contract import (
    build_seed_index, write_contract, write_seed_index,
)
from src.layers.l3_decision.contract.contract_model import Fact, FactBundle
from src.layers.l3_decision.contract.ledger import append_bundle

CASE_IR = {"module": "demo", "cases": [{
    "id": "CASE-A",
    "groups": [{"group": "CG-A", "cell": "CELL-A-P0",
                "required_layers": ["functional"], "tp_ids": ["TP-1"]}],
    "sva": [], "scb": [], "not_applicable": {},
}]}

OBL = "OBL-GROUP-CASE-A-CG-A-FUNCTIONAL"


def _run(tmp_path: Path, *, contract=True) -> Path:
    root = tmp_path / "run_seed_20260101_000000"
    (root / "coverage").mkdir(parents=True)
    (root / "coverage" / "case_ir.json").write_text(
        json.dumps(CASE_IR), encoding="utf-8")
    if contract:
        write_contract(root, CASE_IR)
    for seed, hits in ((4001, 3), (4002, 0)):
        append_bundle(root, FactBundle(
            bundle_id=f"B-{seed}", tst_id=f"TST-A@{seed}", seed=seed,
            facts=[Fact(type="bin_hit", contract_hash="",
                        tst_id=f"TST-A@{seed}", seed=seed,
                        subject={"case": "CASE-A", "tp": "TP-1",
                                 "cp": "cp_a", "bin": "b0"},
                        value={"hits": hits})]))
    return root


def test_index_maps_each_seed_to_its_discharged_obligations(tmp_path):
    data = build_seed_index(_run(tmp_path))
    assert data["available"] is True
    rows = {(r["seed"], r["tst_id"]): r for r in data["seeds"]}
    assert rows[(4001, "TST-A@4001")]["discharged"] == [OBL]
    assert rows[(4002, "TST-A@4002")]["discharged"] == []
    assert rows[(4002, "TST-A@4002")]["remaining"] == [OBL]
    assert data["by_seed"]["4001"]["count"] == 1
    assert data["by_seed"]["4002"]["count"] == 0


def test_index_counts(tmp_path):
    counts = build_seed_index(_run(tmp_path))["counts"]
    assert counts == {"runs": 2, "seeds": 2, "discharged_total": 1}


def test_without_contract_is_unavailable(tmp_path):
    data = build_seed_index(_run(tmp_path, contract=False))
    assert data["available"] is False
    assert data["reason"] == "contract_missing"


def test_write_lands_the_artifact(tmp_path):
    root = _run(tmp_path)
    write_seed_index(root)
    doc = json.loads((root / "status" / "seed_index.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "os_seed_index_v1"
