"""`run_signoff` 的契约。

钉四件事：
  · 门禁按固定顺序读出来，附注键（rtl_files / model_placeholder_reason）不当门禁；
  · 证据链六层带中文层名与检查项，`signoff_ready` 透传；
  · 两份文件**任缺一份都不算错** —— 如实标 `available: false`，不冒充通过；
  · 目录不在 / 空路径 → `{"error"}`，不抛。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.interfaces.api.flow import run_signoff

REPORT = {
    "verdict": "NEEDS_FIX", "pass_rate": "5/6", "coverage": 93.0,
    "signoff_status": "CONDITIONAL",
    "gates": {
        "rtl_present": True, "rtl_files": ["apb_uart.sv", "top.sv"],
        "rtl_real": True, "regression_passed": False,
        "coverage_collected": True,
        "model_real": False, "model_placeholder_reason": "模板占位",
    },
}
CHAIN = {
    "layers": {
        "requirement_layer": {"description": "MD 规格→需求树", "passed": 2, "total": 2,
                              "checks": {"req_spec_completeness": True,
                                         "req_test_mapping": True}, "evidence": {}},
        "verification_layer": {"description": "需求→UVM 用例", "passed": 1, "total": 4,
                               "checks": {"case_coverage_P0": True, "case_coverage_P1": False,
                                          "case_coverage_P2": False, "case_coverage_P3": True},
                               "evidence": {}},
    },
    "checks_passed": 3, "checks_total": 6,
    "signoff_ready": False, "overall_status": "FAIL",
}


def _run_dir(tmp_path: Path, *, report=True, chain=True) -> str:
    root = tmp_path / "apb_uart"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    if report:
        (root / "report.json").write_text(json.dumps(REPORT, ensure_ascii=False),
                                          encoding="utf-8")
    if chain:
        (root / "docs" / "evidence_chain.json").write_text(
            json.dumps(CHAIN, ensure_ascii=False), encoding="utf-8")
    return str(root)


class TestGates:
    def test_gate_order_is_fixed(self, tmp_path):
        result = run_signoff(_run_dir(tmp_path))
        assert [g["id"] for g in result["gates"]["rows"]] == \
            ["rtl_present", "rtl_real", "regression_passed",
             "coverage_collected", "model_real"]

    def test_notes_are_not_treated_as_gates(self, tmp_path):
        ids = {g["id"] for g in run_signoff(_run_dir(tmp_path))["gates"]["rows"]}
        assert "rtl_files" not in ids
        assert "model_placeholder_reason" not in ids

    def test_pass_and_fail_are_read(self, tmp_path):
        rows = {g["id"]: g for g in run_signoff(_run_dir(tmp_path))["gates"]["rows"]}
        assert rows["rtl_present"]["passed"] is True
        assert rows["regression_passed"]["passed"] is False
        assert rows["model_real"]["passed"] is False

    def test_detail_carries_the_why(self, tmp_path):
        rows = {g["id"]: g for g in run_signoff(_run_dir(tmp_path))["gates"]["rows"]}
        assert "2 个 .sv" in rows["rtl_present"]["detail"]
        assert "5/6" in rows["regression_passed"]["detail"]
        assert "占位" in rows["model_real"]["detail"]

    def test_verdict_and_rate(self, tmp_path):
        result = run_signoff(_run_dir(tmp_path))
        assert result["verdict"] == "NEEDS_FIX"
        assert result["signoff_status"] == "CONDITIONAL"
        assert result["pass_rate"] == "5/6"
        assert result["coverage"] == 93.0


class TestChain:
    def test_layers_carry_chinese_titles(self, tmp_path):
        layers = {L["id"]: L for L in run_signoff(_run_dir(tmp_path))["chain"]["layers"]}
        assert layers["requirement_layer"]["title"] == "需求层"
        assert layers["verification_layer"]["title"] == "验证层"

    def test_checks_are_named(self, tmp_path):
        layers = {L["id"]: L for L in run_signoff(_run_dir(tmp_path))["chain"]["layers"]}
        names = [c["title"] for c in layers["verification_layer"]["checks"]]
        assert "P0 用例覆盖" in names

    def test_signoff_ready_is_passed_through(self, tmp_path):
        chain = run_signoff(_run_dir(tmp_path))["chain"]
        assert chain["available"] is True
        assert chain["signoff_ready"] is False
        assert chain["checks_passed"] == 3 and chain["checks_total"] == 6


class TestPartialData:
    def test_missing_report_is_not_an_error(self, tmp_path):
        result = run_signoff(_run_dir(tmp_path, report=False))
        assert "error" not in result
        assert result["gates"]["available"] is False
        assert result["chain"]["available"] is True

    def test_missing_chain_is_not_an_error(self, tmp_path):
        result = run_signoff(_run_dir(tmp_path, chain=False))
        assert "error" not in result
        assert result["chain"]["available"] is False
        assert result["gates"]["available"] is True

    def test_both_missing_says_so(self, tmp_path):
        result = run_signoff(_run_dir(tmp_path, report=False, chain=False))
        assert "error" not in result
        assert "还没有签核信息" in result["summary"]


class TestSummary:
    def test_not_ready_when_gate_fails(self, tmp_path):
        summary = run_signoff(_run_dir(tmp_path))["summary"]
        assert summary.startswith("暂不可签核")
        assert "3/5" in summary          # 门禁 5 道里 3 道过
        assert "证据链未闭合 3/6" in summary

    def test_ready_only_when_both_pass(self, tmp_path):
        root = Path(_run_dir(tmp_path))
        (root / "report.json").write_text(json.dumps(
            {"verdict": "READY", "signoff_status": "APPROVED", "pass_rate": "6/6",
             "coverage": 96.0,
             "gates": {"rtl_present": True, "rtl_real": True,
                       "regression_passed": True, "coverage_collected": True,
                       "model_real": True}}, ensure_ascii=False), encoding="utf-8")
        (root / "docs" / "evidence_chain.json").write_text(json.dumps(
            {"layers": {"signoff_layer": {"description": "签核", "passed": 1, "total": 1,
                                          "checks": {"x": True}, "evidence": {}}},
             "checks_passed": 1, "checks_total": 1, "signoff_ready": True,
             "overall_status": "PASS"}, ensure_ascii=False), encoding="utf-8")
        summary = run_signoff(str(root))["summary"]
        assert summary.startswith("可以签核")
        assert "门禁 5/5 通过" in summary
        assert "证据链闭合" in summary


class TestFailureIsLoud:
    def test_empty_path(self):
        assert "error" in run_signoff("")

    def test_missing_dir(self, tmp_path):
        result = run_signoff(str(tmp_path / "nope"))
        assert "error" in result and "不存在" in result["error"]

    def test_path_is_a_file(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("hi", encoding="utf-8")
        assert "error" in run_signoff(str(f))

    def test_broken_json_is_treated_as_missing(self, tmp_path):
        root = Path(_run_dir(tmp_path))
        (root / "report.json").write_text("{ not json", encoding="utf-8")
        result = run_signoff(str(root))
        assert "error" not in result
        assert result["gates"]["available"] is False

    def test_never_raises(self):
        for bad in ("", "nope", "\x00"):
            assert isinstance(run_signoff(bad), dict)


class TestTestpointsSummary:
    """签核页的测试点口径 —— 由 audit 写进 `report.json`，这里只透传。"""

    def _with_tp(self, tmp_path: Path) -> str:
        report = dict(REPORT)
        report["testpoints"] = {"total": 63, "drivable": 26, "drivable_hit": 16,
                                "drivable_pct": 61.54, "observe_only": 37,
                                "observed": 25, "missed": 22, "unmapped": 0}
        report["caveats"] = ["约束只部分生效：5/11 条策略有真实赋值"]
        root = Path(_run_dir(tmp_path, chain=False))
        (root / "report.json").write_text(json.dumps(report, ensure_ascii=False),
                                          encoding="utf-8")
        return str(root)

    def test_summary_and_caveats_are_passed_through(self, tmp_path):
        result = run_signoff(self._with_tp(tmp_path))
        assert result["testpoints"]["drivable_hit"] == 16
        assert result["testpoints"]["drivable_pct"] == 61.54
        assert result["caveats"] == ["约束只部分生效：5/11 条策略有真实赋值"]

    def test_an_old_report_has_empty_summary_not_a_fake_one(self, tmp_path):
        """老 run 没有这个字段 —— 如实给空，不编一个"全过"。"""
        result = run_signoff(_run_dir(tmp_path))
        assert result["testpoints"] == {}
        assert result["caveats"] == []
