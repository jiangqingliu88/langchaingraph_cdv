"""M2b：case 级判定交给 derive —— 采集端只给原始事实。

停点：同一份执行切片，`judge_case()` 的结论与改造前 `case_cov` 的判定逐字段
一致（本仓库用真实 run 做过 267 份逐文件对账，这里钉住语义本身）。
"""
from __future__ import annotations

from src.ir.contract.case_judge import (
    build_raw_facts, judge_case,
)
from src.ir.contract.derive import tp_contract_status

CASE_IR = {
    "module": "demo",
    "cases": [{
        "id": "CASE-A",
        "groups": [{
            "group": "CG-A", "cell": "CELL-A-P0",
            "required_layers": ["functional", "timing", "data"],
            "tp_ids": ["TP-1"],
        }],
        "sva": [{"id": "SVA-X", "name": "x", "cell": "CELL-A-P0"}],
        "scb": [{"id": "SB-X", "cell": "CELL-A-P0", "evidence": "aggregate"}],
    }],
}


def _judge(*, hits=2, present=True, fail=0, matched=5, mismatched=0, timing=True):
    facts = build_raw_facts(
        "CASE-A",
        bins=[{"tp": "TP-1", "cp": "cp_a", "bin": "b0", "hits": hits}],
        sva=[{"id": "SVA-X", "present": present, "fail": fail}],
        scb=[{"id": "aggregate", "exec": 5, "matched": matched,
              "mismatched": mismatched},
             {"id": "SB-X", "exec": 5, "matched": matched,
              "mismatched": mismatched}],
        timing_ok=timing,
    )
    return judge_case(CASE_IR, "CASE-A", facts)


def test_all_layers_proven_gives_verified():
    judged = _judge()
    assert judged["case_status"] == "VERIFIED"
    assert judged["groups"]["CG-A"]["result"] == "PROVEN"


def test_missed_bin_is_partial():
    judged = _judge(hits=0)
    assert judged["groups"]["CG-A"]["layers"]["functional"] == "MISSING"
    assert judged["case_status"] == "NOT_VERIFIED"


def test_undeclared_timing_is_not_applicable_not_pass():
    """时序没声明 = NA（不是"通过"）；组结果按 worst 排除 NA（与改造前同口径）。"""
    judged = _judge(timing=None)
    assert judged["groups"]["CG-A"]["layers"]["timing"] == "NOT_APPLICABLE"
    assert judged["groups"]["CG-A"]["result"] == "PROVEN"


def test_assertion_never_evaluated_is_missing():
    judged = _judge(present=False, fail=None)
    assert judged["sva"]["SVA-X"] == "MISSING"
    assert judged["case_status"] == "NOT_VERIFIED"


def test_scb_mismatch_is_missing():
    judged = _judge(matched=4, mismatched=1)
    assert judged["groups"]["CG-A"]["layers"]["data"] == "MISSING"


def test_no_contract_returns_none():
    assert judge_case({}, "CASE-A", []) is None
    assert judge_case(CASE_IR, "CASE-MISSING", []) is None


class TestTpContractStatusIsSingleSourced:
    def test_four_layers_decide_verified(self):
        layers = {k: {"status": "PROVEN"} for k in ("functional", "timing", "data")}
        layers["path"] = {"status": "NOT_APPLICABLE"}
        assert tp_contract_status(layers) == "VERIFIED"

    def test_na_layer_caps_at_partial(self):
        layers = {k: {"status": "PROVEN"} for k in ("functional", "data")}
        layers["timing"] = {"status": "NOT_APPLICABLE"}
        layers["path"] = {"status": "NOT_APPLICABLE"}
        assert tp_contract_status(layers) == "PARTIAL"

    def test_behavior_is_pending(self):
        assert tp_contract_status({}, "behavior") == "PENDING_BACKEND"


def test_pipeline_orders_cell_matrix_before_evd():
    """EVD 要读 cell_matrix 反查 CELL —— 顺序反了，新 run 的 EVD 行全是空 cells。"""
    from src.layers.l3_decision.evidence.evidence_pipeline import STEPS

    assert STEPS.index("cell_matrix") < STEPS.index("evd")
