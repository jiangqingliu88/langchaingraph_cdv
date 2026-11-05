"""M1：契约是构建物 —— 编译、校验、漂移检测、ops 门禁。

停点（计划 M1）：没有契约时 ops 拒绝开跑；契约被改过就核不过；
历史/手工 run（没有 TP IR）不被误伤。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.layers.l3_decision.contract import (
    check_contract, contract_hash, load_contract, read_manifest, write_contract,
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


def _run(tmp_path: Path, *, testpoints: bool = True) -> Path:
    root = tmp_path / "run_contract_20260101_000000"
    (root / "coverage").mkdir(parents=True)
    (root / "coverage" / "case_ir.json").write_text(
        json.dumps(CASE_IR, ensure_ascii=False), encoding="utf-8")
    if testpoints:
        (root / "coverage" / "testpoints.yaml").write_text(
            "version: '1.0'\ntestpoints: []\n", encoding="utf-8")
    return root


def test_build_writes_contract_obligations_and_manifest(tmp_path):
    root = _run(tmp_path)
    manifest = write_contract(root, CASE_IR)
    for name in ("contract.yaml", "obligations.json", "contract_manifest.json"):
        assert (root / "contract" / name).is_file(), name
    assert manifest["obligations"] == 1
    assert manifest["contract_hash"] == contract_hash(root)
    assert check_contract(root)["ok"] is True


def test_contract_round_trips(tmp_path):
    root = _run(tmp_path)
    write_contract(root, CASE_IR)
    model = load_contract(root)
    assert model is not None and model.cases[0].id == "CASE-A"
    # 读回来的契约重新算哈希，必须与清单一致
    assert model.compute_hash() == read_manifest(root)["contract_hash"]


def test_edited_contract_is_detected(tmp_path):
    root = _run(tmp_path)
    write_contract(root, CASE_IR)
    path = root / "contract" / "contract.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("CASE-A", "CASE-B"),
                    encoding="utf-8")
    result = check_contract(root)
    assert result["ok"] is False
    assert result["reason"] == "contract_hash_mismatch"


def test_missing_contract_is_reported(tmp_path):
    root = _run(tmp_path)
    assert check_contract(root)["reason"] == "contract_missing"


class TestOpsGate:
    def test_blocks_when_contract_missing_but_tp_ir_present(self, tmp_path):
        from src.executors.ops.main import _contract_gate

        root = _run(tmp_path)
        gate = _contract_gate(root, {})
        assert gate is not None and gate.success is False
        assert gate.data["regression"]["contract_missing"] is True

    def test_passes_after_build(self, tmp_path):
        from src.executors.ops.main import _contract_gate

        root = _run(tmp_path)
        write_contract(root, CASE_IR)
        assert _contract_gate(root, {}) is None

    def test_legacy_run_without_tp_ir_is_not_blocked(self, tmp_path):
        from src.executors.ops.main import _contract_gate

        root = _run(tmp_path, testpoints=False)
        assert _contract_gate(root, {}) is None

    def test_explicit_bypass(self, tmp_path, monkeypatch):
        from src.executors.ops.main import _contract_gate

        root = _run(tmp_path)
        assert _contract_gate(root, {"contract_gate": False}) is None
        monkeypatch.setenv("SIGNOFFAI_CONTRACT_GATE", "off")
        assert _contract_gate(root, {}) is None
