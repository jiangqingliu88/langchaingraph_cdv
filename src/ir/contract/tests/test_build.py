"""M1：契约是构建物 —— 编译、校验、漂移检测、ops 门禁。

停点（计划 M1）：没有契约时 ops 拒绝开跑；契约被改过就核不过；
历史/手工 run（没有 TP IR）不被误伤。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.ir.contract import (
    check_contract, contract_hash, load_contract, read_manifest, write_contract,
)
from src.ir.contract.build import ensure_vplan_map

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


def test_vplan_map_links_contracts_to_obligations(tmp_path):
    """VPlan `C-*` → 环境契约（CASE / OBL / 资产）的 sidecar 映射。

    `vplan gate` 用它在 `verify` 之后按义务状态判 VPlan 契约；映射本身
    不参与契约哈希（改映射不会让旧证据失效）。
    """
    case_ir = {
        "module": "demo",
        "cases": [{
            "id": "TC-A",
            "feats": ["C-FUNC-UNIT-001", "C-IF-HS-001"],
            "groups": [{"group": "CG-A", "cell": "CELL-A-P0",
                        "required_layers": ["functional"],
                        "tp_ids": ["TP-1"]}],
            "sva": [{"id": "foo_sva"}],
            "scb": [{"id": "foo_scb"}],
        }],
    }
    root = tmp_path / "run_map"
    manifest = write_contract(root, case_ir)
    doc = json.loads((root / "contract" / "vplan_map.json")
                     .read_text(encoding="utf-8"))
    assert doc["schema"] == "vplan_contract_map_v1"
    slot = doc["contracts"]["C-FUNC-UNIT-001"]
    assert slot["cases"] == ["TC-A"]
    assert slot["artifacts"] == ["CG-A", "foo_sva", "foo_scb"]
    assert len(slot["obligations"]) == manifest["obligations"]
    # 同一 case 引用的每个 C-* 映射到同一组义务（引用不复制字段）。
    assert doc["contracts"]["C-IF-HS-001"] == slot
    # 映射是 sidecar：契约哈希只由 contract.yaml 决定。
    assert manifest["contract_hash"] == contract_hash(root)


def test_ensure_vplan_map_backfills_old_runs(tmp_path):
    """mapping 上线前的 run：`link` 用 case_ir + obligations 补写 sidecar。"""
    case_ir = {
        "module": "demo",
        "cases": [{"id": "TC-A", "feats": ["C-FUNC-UNIT-001"],
                   "groups": [{"group": "CG-A", "cell": "CELL-A-P0",
                               "required_layers": ["functional"],
                               "tp_ids": ["TP-1"]}]}],
    }
    root = tmp_path / "run_old"
    write_contract(root, case_ir)
    (root / "coverage").mkdir()
    (root / "coverage" / "case_ir.json").write_text(
        json.dumps(case_ir), encoding="utf-8")
    (root / "contract" / "vplan_map.json").unlink()

    assert ensure_vplan_map(root) is True
    doc = json.loads((root / "contract" / "vplan_map.json")
                     .read_text(encoding="utf-8"))
    assert "C-FUNC-UNIT-001" in doc["contracts"]
    # 幂等：已有映射就不再写。
    assert ensure_vplan_map(root) is False


class TestOpsGate:
    def test_blocks_when_contract_missing_but_tp_ir_present(self, tmp_path):
        from src.engine.ops.main import _contract_gate

        root = _run(tmp_path)
        gate = _contract_gate(root, {})
        assert gate is not None and gate.success is False
        assert gate.data["regression"]["contract_missing"] is True

    def test_passes_after_build(self, tmp_path):
        from src.engine.ops.main import _contract_gate

        root = _run(tmp_path)
        write_contract(root, CASE_IR)
        assert _contract_gate(root, {}) is None

    def test_legacy_run_without_tp_ir_is_not_blocked(self, tmp_path):
        from src.engine.ops.main import _contract_gate

        root = _run(tmp_path, testpoints=False)
        assert _contract_gate(root, {}) is None

    def test_explicit_bypass(self, tmp_path, monkeypatch):
        from src.engine.ops.main import _contract_gate

        root = _run(tmp_path)
        assert _contract_gate(root, {"contract_gate": False}) is None
        monkeypatch.setenv("SIGNOFFAI_CONTRACT_GATE", "off")
        assert _contract_gate(root, {}) is None
