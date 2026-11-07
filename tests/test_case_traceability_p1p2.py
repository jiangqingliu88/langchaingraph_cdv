"""P1/P2：测试点位图、`[TP_HIT]`、时序窗口 —— **位序与判据的契约**。

P1 回答"打开波形能不能看到这条波形在证明哪个测试点"：
`coverage/tp_bitmap.json` 的位序 → env 组件置 `cov_vif.tp_seen` + 打 `[TP_HIT]`。

P2 回答"波形里的时序对不对"：TP IR 带 `timing.expect_cycles`，env 检查组逐拍
判窗，超窗打 `[TP_TIMING]`。**没有 timing 的 TP 不判** —— 不编假期望，也不把
"没声明"当"通过"。
"""
from __future__ import annotations

from tests.npu_fixtures import NPU_CASEMODEL, NPU_RTL_DIR

import json
import shutil
from pathlib import Path

import yaml

from src.tools.common.lib import case_meta
from src.layers.l3_decision.casemodel.domain.dimensions import build_dimension
from src.layers.l3_decision.casemodel.framework.model import (
    TestPoint as TpModel, Timing)


# ────────────────────────────────────────────────────────────────
# P2：TP IR 的 timing
# ────────────────────────────────────────────────────────────────

class TestTimingIR:
    def test_common_timing_is_normalized_to_a_star_spec(self):
        dim = build_dimension({
            "id": "D", "fields": [{"name": "x"}],
            "realization": {"kind": "sequence", "timing": {
                "expect_cycles": {"min": 2, "max": 12},
                "start": "load_submit", "end": "issue_valid",
                "tolerance": 1,
            }},
        })
        assert dim.realization_timing["*"]["expect_cycles"] == {"min": 2, "max": 12}
        assert dim.realization_timing["*"]["start"] == "load_submit"

    def test_per_token_timing_is_kept_separate(self):
        dim = build_dimension({
            "id": "D", "fields": [{"name": "x"}],
            "realization": {"kind": "sequence", "timing": {
                "MAC_MAC": {"expect_cycles": {"min": 1, "max": 3}},
                "LOAD_MAC": {"expect_cycles": {"min": 2, "max": 12}},
            }},
        })
        assert set(dim.realization_timing) == {"MAC_MAC", "LOAD_MAC"}

    def test_timing_requires_a_start_and_end_to_be_checkable(self):
        t = Timing.from_dict({"expect_cycles": {"min": 2, "max": 12},
                              "sample": "issue_valid"})
        assert t is not None and t.checkable is False       # 没有 start
        t2 = Timing.from_dict({"expect_cycles": {"min": 2, "max": 12},
                               "start": "load_submit", "sample": "issue_valid"})
        assert t2 is not None and t2.checkable is True

    def test_tp_serialization_carries_timing_only_when_declared(self):
        tp = TpModel(tp_id="TP-1", object="o", dimension="d", value="v",
                       timing=Timing.from_dict({"expect_cycles": {"min": 2, "max": 4},
                                                "start": "a", "end": "b"}))
        assert tp.to_dict()["timing"]["expect_cycles"] == {"min": 2, "max": 4}
        assert "timing" not in TpModel(
            tp_id="TP-2", object="o", dimension="d", value="v").to_dict()


# ────────────────────────────────────────────────────────────────
# P1：位图 + 接口
# ────────────────────────────────────────────────────────────────

class TestTpBitmap:
    def _payloads(self):
        tp_payload = {"testpoints": [
            {"tp_id": "TP-A", "coverpoint": "cp_x", "bin": "b0",
             "realization": {"kind": "stimulus", "agent": "ag"},
             "timing": {"expect_cycles": {"min": 2, "max": 5},
                        "start": "a", "end": "b", "tolerance": 1}},
            {"tp_id": "TP-B", "coverpoint": "cp_d", "bin": "mid",
             "realization": {"kind": "observe"}},
            {"tp_id": "TP-C", "coverpoint": "", "bin": "",
             "realization": {"kind": "observe"}},
        ]}
        cov_payload = {"coverpoints": [
            {"cp_name": "cp_x", "source": "stimulus", "signal": "x",
             "bins": [{"name": "b0", "literal": "0"}]},
            {"cp_name": "cp_d", "source": "dut", "signal": "d",
             "bins": [{"name": "mid", "literal": "[1:7]"}]},
        ]}
        return tp_payload, cov_payload

    def test_bits_follow_testpoint_order_and_carry_the_bin_literal(self):
        from src.executors.verify.main import _build_tp_bitmap

        tp, cov = self._payloads()
        bmp = _build_tp_bitmap(tp, cov, {"ag": ["x"]})
        assert bmp["width"] == 3
        assert [e["bit"] for e in bmp["entries"]] == [0, 1, 2]
        a, b = bmp["entries"][0], bmp["entries"][1]
        assert a["trackable"] and a["literal"] == "0" and a["agent"] == "ag"
        assert b["trackable"] and b["literal"] == "[1:7]" and b["source"] == "dut"
        # 没有 coverpoint/bin 的（行为域/未追踪）不生成假位
        assert bmp["entries"][2]["trackable"] is False

    def test_timing_window_is_carried_and_checkable(self):
        from src.executors.verify.main import _build_tp_bitmap

        tp, cov = self._payloads()
        bmp = _build_tp_bitmap(tp, cov, {"ag": ["x"]})
        tm = bmp["entries"][0]["timing"]
        assert tm == {"min": 2, "max": 5, "tolerance": 1,
                      "start": "a", "end": "b", "sample": "", "checkable": True}
        assert "timing" not in bmp["entries"][1]

    def test_auto_binned_bin_is_not_trackable(self):
        from src.executors.verify.main import _build_tp_bitmap

        tp = {"testpoints": [{"tp_id": "TP-Z", "coverpoint": "cp_x",
                              "bin": "v_zero",
                              "realization": {"kind": "stimulus"}}]}
        cov = {"coverpoints": [{"cp_name": "cp_x", "source": "stimulus",
                                "signal": "x", "bins": []}]}
        bmp = _build_tp_bitmap(tp, cov, {"ag": ["x"]})
        assert bmp["entries"][0]["trackable"] is False
        assert "自动分箱" in bmp["entries"][0]["note"]

    def test_open_range_is_not_trackable(self):
        from src.executors.verify.main import _build_tp_bitmap

        tp = {"testpoints": [{"tp_id": "TP-Z", "coverpoint": "cp_x",
                              "bin": "b0",
                              "realization": {"kind": "stimulus"}}]}
        cov = {"coverpoints": [{"cp_name": "cp_x", "source": "stimulus",
                                "signal": "x",
                                "bins": [{"name": "b0", "literal": "[8:$]"}]}]}
        bmp = _build_tp_bitmap(tp, cov, {"ag": ["x"]})
        assert bmp["entries"][0]["trackable"] is False

    def test_interface_gets_tp_seen_when_width_is_given(self):
        from src.layers.l3_decision.casemodel.api import run_covergroups

        text = NPU_CASEMODEL.read_text(encoding="utf-8")
        p = run_covergroups(text, "npu_sched", tp_bitmap_width=70)
        code = p["cov_interface_code"]
        assert "logic [69:0] tp_seen;" in code
        assert p["cov_interface"]["tp_bitmap_width"] == 70


# ────────────────────────────────────────────────────────────────
# 模板：tp_seen / [TP_HIT] / [TP_TIMING]
# ────────────────────────────────────────────────────────────────

class TestEnvTemplateRendersTheTrace:
    def _render(self, tmp_path, bitmap):
        ydir = tmp_path / "inputs" / "yaml" / "uvm"
        ydir.mkdir(parents=True)
        for src in Path("src/tools/generation/uvm_tools/tool_uvm/examples/apb").glob("*.yaml"):
            shutil.copy(src, ydir / src.name)
        payload = {
            "cov_bins": [],
            "dut_if": {
                "name": "apb_slave_cov_if", "type": "apb_slave_cov_if",
                "instance": "u_apb_slave_cov_if", "dut_module": "apb_slave_dut",
                "clock": "pclk", "reset": "presetn",
                "file": "coverage/apb_slave_cov_if.sv",
                "signals": ["paddr"], "tp_bitmap_width": bitmap["width"],
                "coverpoints": [{"signal": "paddr", "sv_name": "cp_paddr",
                                 "field": "paddr", "width": 8, "expr": ""}],
            },
            "dut_bins": {"paddr": [
                {"name": "cp_zero", "value": "0", "illegal": False},
                {"name": "cp_mid", "value": "[1:127]", "illegal": False},
            ]},
            "tp_bitmap": bitmap,
        }
        (ydir / "env_cov_bins.yaml").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        from src.tools.generation.uvm_tools.tool_jinja_render.main import run

        assert json.loads(run(str(tmp_path)))["status"] == "ok"
        env = list((tmp_path / "env").glob("*_coverage.sv"))
        assert len(env) == 1
        return env[0].read_text(encoding="utf-8")

    def test_tp_hit_tp_seen_and_tp_timing_all_render(self, tmp_path):
        bitmap = {"schema": "tp_bitmap_v1", "width": 2, "entries": [
            {"bit": 0, "tp_id": "TP-A", "coverpoint": "cp_paddr", "bin": "cp_zero",
             "kind": "stimulus", "source": "stimulus", "agent": "apb_master",
             "signal": "paddr", "literal": "0", "trackable": True, "note": ""},
            {"bit": 1, "tp_id": "TP-B", "coverpoint": "cp_paddr", "bin": "cp_mid",
             "kind": "sequence", "source": "dut", "agent": "",
             "signal": "paddr", "literal": "[1:127]", "trackable": True, "note": "",
             "timing": {"min": 2, "max": 12, "tolerance": 0,
                        "start": "paddr", "end": "pwrite", "sample": "pwrite",
                        "checkable": True}},
        ]}
        env = self._render(tmp_path, bitmap)
        assert "bit [1:0] tp_hit_logged = '0;" in env
        assert "cov_vif.tp_seen[0] = 1'b1;" in env
        assert '`uvm_info("TP_HIT"' in env
        assert "tp=TP-A cp=cp_paddr bin=cp_zero" in env
        assert '`uvm_warning("TP_TIMING"' in env        # sequence → 只 WARN
        assert "checked=1 violations=%0d" in env
        assert "inside {0}" in env and "inside {[1:127]}" in env


# ────────────────────────────────────────────────────────────────
# 日志 → timing_ok → 签核
# ────────────────────────────────────────────────────────────────

TIMING_LOG = """\
UVM_INFO @ 10: [TP_HIT] tp=TP-A cp=cp_x bin=b0 t=100
UVM_WARNING @ 20: [TP_TIMING] tp=TP-B cycles=4 期望 [2,3]（±0）
UVM_INFO @ 30: [TP_TIMING] checked=2 violations=1
UVW_ERROR :    0
[SCB_DUT] total=4 matched=4 mismatched=0
"""


class TestTimingFactsAndSignoff:
    def test_log_extracts_checked_violations_and_by_tp(self):
        facts = case_meta.parse_case_log(TIMING_LOG.replace("UVW_ERROR", "UVM_ERROR"))
        timing = facts["timing"]
        assert timing["checked"] == 2 and timing["violations"] == 1
        assert timing["by_tp"] == {"TP-B": 1}

    def test_no_timing_line_is_none_not_pass(self):
        facts = case_meta.parse_case_log("UVM_ERROR :    0\n")
        assert facts["timing"]["checked"] is None
        assert facts["timing"]["by_tp"] == {}

    def _facts(self, by_tp, checked=1):
        return {
            "hits": {"cg_dut": {"cp_x": {"b0": 3}}},
            "illegal": {},
            "wave": "/run/waves/t.db",
            "log_facts": {
                "log_ok": True, "uvm_errors": 0, "uvm_fatal": 0,
                "scb": {"total": 4, "matched": 4, "mismatched": 0},
                "assertions": {"rules": 0, "fired": 0},
                "timing": {"checked": checked, "violations": sum(by_tp.values()),
                           "by_tp": by_tp},
            },
        }

    def test_timing_violation_blocks_a_stimulus_tp(self):
        from src.layers.l3_decision.evidence.case_cov import _tp_case_entry

        tp = {"tp_id": "TP-A", "coverpoint": "cp_x", "bin": "b0",
              "realization": {"kind": "stimulus"}}
        e = _tp_case_entry(tp, self._facts({"TP-A": 1}), require_wave=True)
        assert e["timing_ok"] is False
        assert "timing_violation" in e["reasons"]

    def test_timing_violation_only_warns_for_a_sequence_tp(self):
        from src.layers.l3_decision.evidence.case_cov import _tp_case_entry

        tp = {"tp_id": "TP-A", "coverpoint": "cp_x", "bin": "b0",
              "realization": {"kind": "sequence"}}
        e = _tp_case_entry(tp, self._facts({"TP-A": 1}), require_wave=True)
        assert e["timing_ok"] is False
        assert "timing_violation" not in e["reasons"]
        assert e["status"] == "SIGNED_OFF"       # 不否决

    def test_clean_timing_is_true(self):
        from src.layers.l3_decision.evidence.case_cov import _tp_case_entry

        tp = {"tp_id": "TP-A", "coverpoint": "cp_x", "bin": "b0",
              "realization": {"kind": "stimulus"}}
        e = _tp_case_entry(tp, self._facts({}, checked=1), require_wave=True)
        assert e["timing_ok"] is True

    def test_case_level_timing_is_none_when_not_checked(self):
        from src.layers.l3_decision.evidence.case_cov import _case_timing_ok

        assert _case_timing_ok({"log_facts": {"timing": {"checked": None}}}) is None
        assert _case_timing_ok({"log_facts": {"timing": {
            "checked": 1, "violations": 0}}}) is True
        assert _case_timing_ok({"log_facts": {"timing": {
            "checked": 1, "violations": 2}}}) is False

    def test_audit_flags_sequence_timing_warn(self, tmp_path):
        from src.executors.audit.main import _apply_case_coverage_gate

        gates: dict = {}
        caveats: list = []
        _apply_case_coverage_gate(
            tmp_path,
            {"rows": [{"tp_id": "TP-S", "kind": "sequence", "stage": "p1",
                       "signed_off": True, "signed_off_by": "",
                       "timing_ok": False}]},
            gates, lambda code, msg: caveats.append(code))
        assert "TP_TIMING_WARN" in caveats


# ────────────────────────────────────────────────────────────────
# 工作台：测试点列 + 波形归属
# ────────────────────────────────────────────────────────────────

class TestWorkbenchTrace:
    def test_regression_rows_carry_tp_ids_from_the_manifest(self, tmp_path):
        from src.app.services.flow.regression_api import run_regression_status

        d = tmp_path / "regression_run" / "p1" / "build_b" / "test_tp_a_seed_1"
        d.mkdir(parents=True)
        (d / "status.env").write_text("EMAN_BASE_STATUS=pass\n", encoding="utf-8")
        case_meta.write_task_meta(d, {"task": "tp_a_seed_1", "test": "env_attr_test",
                                      "seed": 1, "tp_ids": ["TP-1"]})
        case_meta.write_wave_manifest(tmp_path, [d])

        payload = run_regression_status(str(tmp_path))
        row = next(r for r in payload["rows"] if r["name"] == "tp_a_seed_1")
        assert row["tp_ids"] == ["TP-1"]

    def test_wave_context_comes_from_the_manifest(self, tmp_path):
        from src.workbench.modules.ops.cov_actions import _wave_manifest_context

        run = tmp_path / "run"
        d = run / "regression_run" / "p1" / "build_b" / "test_tp_a_seed_1"
        (d / "waves").mkdir(parents=True)
        (d / "waves" / "tp_a.db").write_bytes(b"w")
        (d / "sim.sh").write_text("+UVM_TESTNAME=env_attr_test\n", encoding="utf-8")
        case_meta.write_task_meta(d, {"task": "tp_a_seed_1", "test": "env_attr_test",
                                      "seed": 1, "tp_ids": ["TP-1"]})
        case_meta.write_wave_manifest(run, [d])

        ctx = _wave_manifest_context(str(d / "waves" / "tp_a.db"))
        assert ctx["task"] == "tp_a_seed_1"
        assert ctx["tp_ids"] == ["TP-1"]

    def test_column_is_registered(self):
        from src.workbench.modules.ops.regression_artifacts import COLUMN_OF
        assert "tp_ids" in COLUMN_OF


def test_schema_registers_the_bitmap():
    schema = json.loads(Path(
        "src/tools/generation/uvm_tools/tool_uvm/schema/uvm_config.schema.json"
    ).read_text(encoding="utf-8"))
    assert "tp_bitmap" in schema["properties"]
    assert "tpBitEntry" in schema["$defs"]
    assert "tp_bitmap_width" in schema["properties"]["dut_if"]["properties"]
