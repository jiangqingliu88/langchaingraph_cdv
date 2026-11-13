"""Fake-EDA integration: Debug tool loop over real log parsing + auto_fix.

No QuestaSim: `collect_sim_log` reads a synthetic `sim_*.log`; `auto_fix`
applies the real `fix_missing_vif` patch; `rerun_failed_test` is a fake tool
that returns PASS, so the loop can be tested end-to-end without EDA.
"""
from __future__ import annotations

import json

from src.engine.diagnostics.main import auto_fix, collect_sim_log
from src.agent.runtime.tool_loop import run_tool_loop


class _FakeRerun:
    name = "rerun_failed_test"
    description = "fake rerun for integration test (no EDA)"

    def __init__(self):
        self.calls = []

    def invoke(self, args):
        self.calls.append(dict(args))
        return json.dumps({"status": "PASS", "test_name": "smoke"})


def test_debug_loop_collect_autofix_rerun(tmp_path):
    run = tmp_path / "run"
    (run / "sim").mkdir(parents=True)
    (run / "sim" / "sim_smoke.log").write_text(
        "UVM_ERROR @ 10ns: virtual interface not set in test.sv(12)\n",
        encoding="utf-8")
    tb = run / "dut_tb_top.sv"
    tb.write_text(
        "module dut_tb_top;\n"
        "  initial begin\n"
        "    run_test();\n"
        "  end\n"
        "endmodule\n",
        encoding="utf-8")

    rerun = _FakeRerun()
    replies = iter([
        json.dumps({"action": "tool", "tool": "collect_sim_log",
                    "args": {"output_dir": str(run)}}),
        json.dumps({"action": "tool", "tool": "auto_fix",
                    "args": {"input_json": json.dumps({
                        "error_text": "virtual interface not set",
                        "output_dir": str(run)})}}),
        json.dumps({"action": "tool", "tool": "rerun_failed_test",
                    "args": {"input_json": json.dumps({
                        "output_dir": str(run), "test_name": "smoke"})}}),
        json.dumps({"action": "final", "answer": "fixed and rerun PASS"}),
    ])
    result = run_tool_loop(
        "fix virtual interface", [collect_sim_log, auto_fix, rerun],
        llm=lambda prompt: next(replies), max_steps=6)

    assert result.ok is True
    assert [c.tool for c in result.tool_calls] == [
        "collect_sim_log", "auto_fix", "rerun_failed_test"]
    assert "logs_scanned" in result.tool_calls[0].observation
    assert '"patch_applied": true' in result.tool_calls[1].observation
    assert "PASS" in result.tool_calls[2].observation
    assert "uvm_config_db" in tb.read_text(encoding="utf-8")
    assert rerun.calls and rerun.calls[0]["input_json"]
