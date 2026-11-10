"""沙箱循环：写只落 staging，出口只有 proposal。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.workspace import WorkspaceZones
from src.workspace.staging import SandboxLoop, SandboxTools


def _zones(tmp_path: Path) -> WorkspaceZones:
    src = tmp_path / "baseline"
    (src / "rtl").mkdir(parents=True)
    (src / "rtl" / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    return WorkspaceZones.init(tmp_path / "ws", src)


def _scripted(decisions):
    queue = list(decisions)

    def llm(payload):
        return queue.pop(0)

    return llm


def test_loop_reads_writes_runs_and_proposes(tmp_path):
    zones = _zones(tmp_path)
    loop = SandboxLoop(zones, llm=_scripted([
        {"thought": "先看文件", "tool": "read_file", "args": {"path": "rtl/a.sv"}},
        {"thought": "改一行", "tool": "write_file",
         "args": {"path": "staging/rtl/a.sv",
                  "content": "module a; // fixed\nendmodule\n"}},
        {"thought": "跑一下", "tool": "run_shell",
         "args": {"command": [sys.executable, "-c", "print('ok')"]}},
        {"thought": "完成", "tool": "propose",
         "args": {"before": "module a; endmodule", "after": "fixed module a",
                  "reasoning_trace": "读到 a.sv，补了边界注释",
                  "open_questions": ["line 47 复位未验证"]}},
    ]))
    result = loop.run("补一个边界用例")

    assert result["status"] == "proposal"
    proposal_id = result["proposal_id"]
    assert (zones.proposal_path(proposal_id)).is_file()
    assert (zones.staging / "rtl" / "a.sv").read_text(encoding="utf-8").startswith(
        "module a; // fixed")
    # main 没被动过
    assert (zones.main / "rtl" / "a.sv").read_text(encoding="utf-8") == \
        "module a; endmodule\n"
    doc = json.loads((zones.proposal_path(proposal_id)).read_text(encoding="utf-8"))
    assert doc["changed_files"][0]["path"] == "staging/rtl/a.sv"
    assert doc["evidence"]["commands"][0]["exit_code"] == 0
    assert doc["evidence"]["logs"][0].startswith("staging/.evidence/")
    assert doc["open_questions"] == ["line 47 复位未验证"]


def test_loop_blocks_honestly_when_llm_is_unavailable(tmp_path, monkeypatch):
    zones = _zones(tmp_path)
    import src.tools.common.lib.llm_call as llm_call
    monkeypatch.setattr(llm_call, "call_llm_messages", lambda *a, **k: "")
    result = SandboxLoop(zones).run("随便做点什么")
    assert result["status"] == "blocked"
    assert "LLM_UNAVAILABLE" in result["reason"]


def test_tools_refuse_to_write_main_or_escape(tmp_path):
    zones = _zones(tmp_path)
    tools = SandboxTools(zones)
    denied = tools.call("write_file", {"path": "main/rtl/a.sv", "content": "x"})
    assert denied["ok"] is False
    escaped = tools.call("write_file", {"path": "../escape.sv", "content": "x"})
    assert escaped["ok"] is False
    assert (zones.main / "rtl" / "a.sv").read_text(encoding="utf-8") == \
        "module a; endmodule\n"


def test_finish_discards_without_proposal(tmp_path):
    zones = _zones(tmp_path)
    loop = SandboxLoop(zones, llm=_scripted([
        {"tool": "write_file",
         "args": {"path": "staging/rtl/scratch.sv", "content": "x"}},
        {"tool": "finish", "args": {"reason": "做不了"}},
    ]))
    result = loop.run("随便做点什么")
    assert result["status"] == "finished_no_proposal"
    assert not list(zones.proposals.glob("*.json"))
    assert (zones.main / "rtl" / "scratch.sv").exists() is False
