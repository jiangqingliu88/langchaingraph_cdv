"""M2 第一步：TP 级状态由「事实 + 推导」算出来，与 `tp_matrix` 对账。

TP 级是**合并库口径**（所有 test 合起来），所以事实来源必须是计划合并报告，
不是单测报告 —— 两边读不同报告，对账全是假差异。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ir.contract.tp_shadow import (
    derive_tp_status, run_facts, run_tp_shadow, status_for_hits,
)

CVG = """\
TYPE /tb/cg_dut
    Coverpoint cp_x           66.66%        100          -    Uncovered
        bin a 12
        bin b 0
    Coverpoint cp_obs        100.00%        100          -    Covered
        bin on 3
"""

TESTPOINTS = {
    "testpoints": [
        {"tp_id": "TP-HIT", "coverpoint": "cp_x", "bin": "a",
         "realization": {"kind": "stimulus"}, "execution": {"stage": "p0"}},
        {"tp_id": "TP-MISS", "coverpoint": "cp_x", "bin": "b",
         "realization": {"kind": "stimulus"}, "execution": {"stage": "p0"}},
        {"tp_id": "TP-UNMAPPED", "coverpoint": "cp_x", "bin": "zz",
         "realization": {"kind": "stimulus"}, "execution": {"stage": "p0"}},
        {"tp_id": "TP-OBS", "coverpoint": "cp_obs", "bin": "on",
         "observe_only": True, "realization": {"kind": "observe"},
         "execution": {"stage": "p1"}},
        {"tp_id": "TP-BD", "coverpoint": "cp_x", "bin": "a",
         "realization": {"kind": "backdoor"}, "execution": {"stage": "p1"}},
        {"tp_id": "TP-BEH", "coverpoint": "cp_x", "bin": "a",
         "realization": {"kind": "behavior"}, "execution": {"stage": "behavior"}},
    ]
}

MATRIX = {"rows": [
    {"tp_id": "TP-HIT", "coverpoint": "cp_x", "bin": "a", "status": "HIT"},
    {"tp_id": "TP-MISS", "coverpoint": "cp_x", "bin": "b", "status": "MISS"},
    {"tp_id": "TP-UNMAPPED", "coverpoint": "cp_x", "bin": "zz", "status": "UNMAPPED"},
    {"tp_id": "TP-OBS", "coverpoint": "cp_obs", "bin": "on", "status": "OBSERVED"},
    {"tp_id": "TP-BD", "coverpoint": "cp_x", "bin": "a", "status": "BACKDOOR_HIT"},
    {"tp_id": "TP-BEH", "coverpoint": "cp_x", "bin": "a", "status": "PENDING_BACKEND"},
]}


def _run(tmp_path: Path, matrix=None) -> Path:
    root = tmp_path / "run_tp_20260101_000000"
    (root / "coverage").mkdir(parents=True)
    (root / "sim" / "coverage" / "reports").mkdir(parents=True)
    (root / "sim" / "coverage" / "reports" / "coverage_cvg.txt").write_text(
        CVG, encoding="utf-8")
    (root / "coverage" / "testpoints.yaml").write_text(
        __import__("yaml").safe_dump(TESTPOINTS, allow_unicode=True), encoding="utf-8")
    (root / "coverage" / "tp_matrix.json").write_text(
        json.dumps(matrix or MATRIX, ensure_ascii=False), encoding="utf-8")
    return root


class TestStatusRule:
    def test_none_is_unmapped_not_zero(self):
        assert status_for_hits(None, "stimulus", False)[0] == "UNMAPPED"

    def test_hit_miss_observe_backdoor(self):
        assert status_for_hits(3, "stimulus", False)[0] == "HIT"
        assert status_for_hits(0, "stimulus", False)[0] == "MISS"
        assert status_for_hits(3, "observe", True)[0] == "OBSERVED"
        assert status_for_hits(0, "observe", True)[0] == "UNOBSERVED"
        assert status_for_hits(1, "backdoor", False)[0] == "BACKDOOR_HIT"
        assert status_for_hits(0, "backdoor", False)[0] == "BACKDOOR_MISS"

    def test_backdoor_flag_is_returned(self):
        _, _, is_bd = status_for_hits(1, "backdoor", False)
        assert is_bd is True


class TestTpShadow:
    def test_facts_come_from_the_merged_report(self, tmp_path):
        root = _run(tmp_path)
        bundle = run_facts(root)
        assert bundle is not None and bundle.facts
        subjects = {(f.subject.get("cp"), f.subject.get("bin"))
                    for f in bundle.facts}
        assert ("cp_x", "a") in subjects and ("cp_x", "b") in subjects

    def test_derivation_reproduces_tp_matrix(self, tmp_path):
        root = _run(tmp_path)
        report = run_tp_shadow(root)
        assert report["ok"] is True, report["diffs"]
        assert report["tps"] == 6

    def test_drift_is_reported(self, tmp_path):
        matrix = json.loads(json.dumps(MATRIX))
        matrix["rows"][0]["status"] = "MISS"        # 旧结论与事实不符
        root = _run(tmp_path, matrix)
        report = run_tp_shadow(root)
        assert report["ok"] is False
        assert report["diffs"][0]["tp_id"] == "TP-HIT"

    def test_behavior_tp_is_pending_without_coverage(self, tmp_path):
        root = _run(tmp_path)
        bundle = run_facts(root)
        ledger = [f.model_dump(by_alias=True) for f in bundle.facts]
        derived = derive_tp_status(TESTPOINTS["testpoints"], ledger)
        assert derived["TP-BEH"]["status"] == "PENDING_BACKEND"

    def test_missing_report_is_not_a_false_negative(self, tmp_path):
        root = _run(tmp_path)
        (root / "sim" / "coverage" / "reports" / "coverage_cvg.txt").unlink()
        report = run_tp_shadow(root)
        assert report["ok"] is False            # 没有报告 = 全部 UNMAPPED → 差异如实报
