"""Verify/Coverage tool-loop and sandbox tests (no EDA, no LLM key)."""
from __future__ import annotations

import asyncio
import json

from src.layers.l2_orchestration.state import PipelineState
from src.agents.coverage.tools import build_coverage_tools
from src.agents.runtime.tool_loop import LoopResult


def test_coverage_tools_read_report_and_write_note(tmp_path):
    run = tmp_path / "run"
    (run / "sim" / "coverage").mkdir(parents=True)
    (run / "sim" / "coverage" / "coverage_result.json").write_text(
        '{"overall_pct": 91.5}', encoding="utf-8")
    tools = {t.name: t for t in build_coverage_tools(run)}

    assert "91.5" in tools["read_coverage"].invoke({})
    listed = json.loads(tools["list_coverage_files"].invoke({}))
    assert "sim/coverage/coverage_result.json" in listed["files"]
    assert json.loads(tools["write_note"].invoke({"content": "gap: opcode"}))["ok"]
    assert (run / "coverage" / "agent_notes.md").is_file()

    assert "error" in json.loads(tools["read_file"].invoke(
        {"path": "../../etc/passwd"}))


def test_verify_loop_is_opt_in_and_fakeable(tmp_path, monkeypatch):
    from src.agents.verify import loop as verify_loop

    monkeypatch.delenv("SIGNOFFAI_VERIFY_LOOP", raising=False)
    off = asyncio.run(verify_loop.n_verify_agent(PipelineState(), {}))
    assert off["verify_agent_loop"]["skipped"] is True

    monkeypatch.setenv("SIGNOFFAI_VERIFY_LOOP", "1")
    monkeypatch.setattr(verify_loop, "run_tool_loop",
                        lambda *a, **k: LoopResult(ok=True, answer="ok", steps=1))
    state = PipelineState(output_root=str(tmp_path), spec={"design_name": "x"})
    on = asyncio.run(verify_loop.n_verify_agent(state, {}))
    assert on["verify_agent_loop"]["ok"] is True


def test_coverage_loop_is_opt_in_and_fakeable(tmp_path, monkeypatch):
    from src.agents.coverage import loop as coverage_loop

    monkeypatch.delenv("SIGNOFFAI_COVERAGE_LOOP", raising=False)
    off = asyncio.run(coverage_loop.n_coverage_agent(PipelineState(), {}))
    assert off["coverage_agent_loop"]["skipped"] is True

    monkeypatch.setenv("SIGNOFFAI_COVERAGE_LOOP", "1")
    monkeypatch.setattr(coverage_loop, "run_tool_loop",
                        lambda *a, **k: LoopResult(ok=True, answer="gaps", steps=1))
    on = asyncio.run(coverage_loop.n_coverage_agent(
        PipelineState(output_root=str(tmp_path), coverage={"overall": 90}), {}))
    assert on["coverage_agent_loop"]["ok"] is True
