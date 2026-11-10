"""Design tool-loop tests: sandbox, opt-in, and RTL gate."""
from __future__ import annotations

import asyncio
import json

from src.agents.supervisor.routing import r_after_design
from src.layers.l2_orchestration.state import PipelineState
from src.agents.design.tools import build_design_tools
from src.agents.runtime.tool_loop import LoopResult


def _tools(root):
    return {t.name: t for t in build_design_tools(root)}


def test_design_tools_are_sandboxed(tmp_path):
    tools = _tools(tmp_path)
    written = json.loads(tools["write_file"].invoke(
        {"path": "x.sv", "content": "module x; endmodule\n"}))
    assert written["ok"] is True
    assert (tmp_path / "rtl" / "x.sv").is_file()

    assert "module x" in tools["read_file"].invoke({"path": "rtl/x.sv"})
    assert json.loads(tools["list_rtl"].invoke({}))["count"] == 1
    check = json.loads(tools["check_rtl"].invoke({}))
    assert check["modules"] == ["x"]

    # 不能逃逸 run 根目录，也不能写非 .sv
    assert "error" in json.loads(tools["write_file"].invoke(
        {"path": "../escape.sv", "content": "x"}))
    assert "error" in json.loads(tools["write_file"].invoke(
        {"path": "x.txt", "content": "x"}))
    assert "error" in json.loads(tools["read_file"].invoke(
        {"path": "../../etc/passwd"}))


def test_design_loop_opt_in_writes_rtl(tmp_path, monkeypatch):
    from src.agents.design import loop as design_loop

    monkeypatch.setenv("SIGNOFFAI_DESIGN_LOOP", "1")
    state = PipelineState(output_root=str(tmp_path), rtl_missing=True,
                          spec={"design_name": "x"})

    def fake_loop(*args, **kwargs):
        (tmp_path / "rtl").mkdir()
        (tmp_path / "rtl" / "x.sv").write_text(
            "module x; endmodule\n", encoding="utf-8")
        return LoopResult(ok=True, answer="wrote x", steps=2)

    monkeypatch.setattr(design_loop, "run_tool_loop", fake_loop)
    out = asyncio.run(design_loop.n_design_agent(state, {}))
    assert out["rtl_missing"] is False
    assert out["design_agent_loop"]["ok"] is True


def test_design_loop_skips_when_rtl_exists(tmp_path, monkeypatch):
    from src.agents.design import loop as design_loop

    monkeypatch.setenv("SIGNOFFAI_DESIGN_LOOP", "1")
    out = asyncio.run(design_loop.n_design_agent(
        PipelineState(output_root=str(tmp_path), rtl_missing=False), {}))
    assert out["design_agent_loop"]["skipped"] is True


def test_rtl_gate_blocks_when_still_missing():
    assert r_after_design(PipelineState(rtl_missing=True)) == "abort"
    assert r_after_design(PipelineState(rtl_missing=False)) == "ok"
