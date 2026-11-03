"""Verification OS v3 内核：契约 / 义务 / 账本 / 推导。

这些测试不跑 EDA、不读 run 目录 —— 只钉住四条不变量里的三条：
契约可哈希、事实只追加（带链）、状态只推导（纯函数）。
"""
from __future__ import annotations

import json

import pytest

from src.tools.checking.verification_os import (
    FACT_TYPES, Contract, Fact, FactBundle, Obligation, Predicate,
    append_bundle, canonical_hash, case_statuses, compile_obligations,
    contract_from_case_ir, derive, read_ledger, verify_chain,
)

CASE_IR = {
    "module": "demo",
    "cases": [{
        "id": "CASE-A",
        "groups": [{
            "group": "CG-A", "name": "功能A", "cell": "CELL-A-P0",
            "required_layers": ["functional", "timing", "data"],
            "tp_ids": ["TP-1", "TP-2"],
        }],
        "sva": [{"id": "SVA-X", "name": "x", "expr": "a |-> b", "cell": "CELL-A-P0"}],
        "scb": [{"id": "SB-X", "cell": "CELL-A-P0", "evidence": "aggregate"}],
        "not_applicable": {},
    }],
}


def _contract() -> Contract:
    return contract_from_case_ir(CASE_IR)


def _facts(case="CASE-A", hits=None, timing=True, scb=("PROVEN", 10, 0),
           sva="PROVEN") -> list:
    contract = _contract()
    facts = []
    for tp, values in (hits or {"TP-1": [3], "TP-2": [2]}).items():
        for i, n in enumerate(values):
            facts.append(Fact(type="bin_hit", contract_hash=contract.hash,
                              subject={"case": case, "tp": tp, "cp": "cp", "bin": f"b{i}"},
                              value={"hits": n}))
    facts.append(Fact(type="timing", contract_hash=contract.hash,
                      subject={"case": case}, value={"ok": timing}))
    status, matched, mismatched = scb
    facts.append(Fact(type="scb_result", contract_hash=contract.hash,
                      subject={"case": case, "id": "aggregate"},
                      value={"status": status, "exec": 10,
                             "matched": matched, "mismatched": mismatched}))
    facts.append(Fact(type="sva_result", contract_hash=contract.hash,
                      subject={"case": case, "id": "SVA-X"},
                      value={"status": sva,
                             "present": sva != "MISSING",
                             "fail": 0 if sva != "MISSING" else None}))
    return [f.model_dump(by_alias=True) for f in facts]


class TestContract:
    def test_hash_is_stable_and_changes_with_content(self):
        first = _contract()
        assert first.hash == _contract().hash
        changed = json.loads(json.dumps(CASE_IR))
        changed["cases"][0]["groups"][0]["name"] = "改过"
        assert contract_from_case_ir(changed).hash != first.hash

    def test_unknown_evidence_layer_is_rejected(self):
        bad = json.loads(json.dumps(CASE_IR))
        bad["cases"][0]["groups"][0]["required_layers"] = ["functional", "magic"]
        with pytest.raises(ValueError, match="未知证据层"):
            contract_from_case_ir(bad)

    def test_unknown_fact_type_is_rejected(self):
        with pytest.raises(ValueError, match="未知事实类型"):
            Predicate(fact_type="made_up", op="x")
        assert "bin_hit" in FACT_TYPES


class TestCompiler:
    def test_one_obligation_per_group_layer_and_checker(self):
        obligations = compile_obligations(_contract())
        kinds = [o.kind for o in obligations]
        assert kinds.count("group_layer") == 3     # functional / timing / data
        assert kinds.count("sva") == 1
        assert kinds.count("scb") == 1

    def test_obligation_ids_are_deterministic(self):
        a = [o.obligation_id for o in compile_obligations(_contract())]
        b = [o.obligation_id for o in compile_obligations(_contract())]
        assert a == b and len(set(a)) == len(a)
        assert a[0].startswith("OBL-")

    def test_predicates_only_reference_declared_fact_types(self):
        for obligation in compile_obligations(_contract()):
            assert obligation.predicate.fact_type.value in FACT_TYPES


class TestLedger:
    def test_append_read_and_chain_ok(self, tmp_path):
        bundle = FactBundle(bundle_id="B-1", tst_id="TST-A@1", seed=1,
                            contract_hash="h", facts=[
                                Fact(type="timing", contract_hash="h",
                                     subject={"case": "CASE-A"}, value={"ok": True})])
        first = append_bundle(tmp_path, bundle)
        assert first["appended"] and first["facts"] == 1
        assert verify_chain(tmp_path)["ok"]
        assert len(read_ledger(tmp_path)) == 1

    def test_duplicate_bundle_is_not_appended_twice(self, tmp_path):
        bundle = FactBundle(bundle_id="B-1", contract_hash="h", facts=[
            Fact(type="timing", contract_hash="h", subject={"case": "C"}, value={})])
        append_bundle(tmp_path, bundle)
        second = append_bundle(tmp_path, bundle)
        assert second["appended"] is False
        assert len(read_ledger(tmp_path)) == 1

    def test_tampering_breaks_the_chain(self, tmp_path):
        bundle = FactBundle(bundle_id="B-1", contract_hash="h", facts=[
            Fact(type="timing", contract_hash="h", subject={"case": "C"}, value={"ok": True})])
        append_bundle(tmp_path, bundle)
        path = tmp_path / "evidence" / "ledger.jsonl"
        doc = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        doc["value"]["ok"] = False          # 手改事实
        path.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
        result = verify_chain(tmp_path)
        assert not result["ok"]
        assert any(i["check"] == "hash_mismatch" for i in result["issues"])


class TestDerive:
    def test_all_bins_hit_is_proven(self):
        obligations = compile_obligations(_contract())
        statuses = derive(obligations, _facts())
        group = [s for k, s in statuses.items() if "GROUP" in k and "FUNCTIONAL" in k]
        assert group == ["PROVEN"]

    def test_missing_bin_is_partial(self):
        obligations = compile_obligations(_contract())
        statuses = derive(obligations, _facts(hits={"TP-1": [3, 0], "TP-2": [2]}))
        group = [s for k, s in statuses.items() if "GROUP" in k and "FUNCTIONAL" in k]
        assert group == ["PARTIAL"]

    def test_no_facts_is_missing_but_undeclared_layers_are_na(self):
        obligations = compile_obligations(_contract())
        statuses = derive(obligations, [])
        # 功能覆盖 / 断言：没有事实 = 没证明（MISSING）
        assert statuses["OBL-GROUP-CASE-A-CG-A-FUNCTIONAL"] == "MISSING"
        assert statuses["OBL-SVA-CASE-A-SVA-X"] == "MISSING"
        # 时序 / 比对：这一轮没声明、没采集 —— NA，不是失败（也不是通过）
        assert statuses["OBL-GROUP-CASE-A-CG-A-TIMING"] == "NOT_APPLICABLE"
        assert statuses["OBL-SCB-CASE-A-SB-X"] == "NOT_EXECUTED"

    def test_timing_not_declared_is_not_applicable(self):
        obligations = compile_obligations(_contract())
        statuses = derive(obligations, _facts(timing=None))
        timing = [s for k, s in statuses.items() if "TIMING" in k]
        assert timing == ["NOT_APPLICABLE"]

    def test_scb_mismatch_is_missing(self):
        obligations = compile_obligations(_contract())
        statuses = derive(obligations, _facts(scb=("MISSING", 9, 1)))
        data = [s for k, s in statuses.items() if "DATA" in k]
        assert data == ["MISSING"]

    def test_case_status_is_worst_of_layers(self):
        obligations = compile_obligations(_contract())
        statuses = derive(obligations, _facts(timing=None))
        slot = case_statuses(obligations, statuses)["CASE-A"]
        assert slot["case_status"] == "VERIFIED"      # NA 不算失败
        statuses = derive(obligations, _facts(sva="MISSING"))
        assert case_statuses(obligations, statuses)["CASE-A"]["case_status"] == "NOT_VERIFIED"


class TestCanonicalHash:
    def test_key_order_does_not_matter(self):
        assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
