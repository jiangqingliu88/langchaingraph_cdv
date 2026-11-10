"""目标分解 + ReAct：每个子目标一轮，complete_subgoal 要证据说明。"""
from __future__ import annotations

import sys
from pathlib import Path

from src.workspace import WorkspaceZones
from src.workspace.harness import Harness, HarnessConfig
from src.workspace.gate import run_gate


def _zones(tmp_path: Path) -> WorkspaceZones:
    src = tmp_path / "baseline"
    (src / "rtl").mkdir(parents=True)
    (src / "rtl" / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    return WorkspaceZones.init(tmp_path / "ws", src)


def _scripted(decisions):
    queue = list(decisions)
    return lambda payload: queue.pop(0)


def test_decompose_and_finish_each_subgoal(tmp_path):
    zones = _zones(tmp_path)
    decisions = [
        {"thought": "拆目标", "tool": "read_file", "args": {"path": "rtl/a.sv"},
         "subgoals": [
             {"id": "G1", "title": "读基线", "success": "知道当前实现"},
             {"id": "G2", "title": "写并验证", "success": "新 case 跑通"},
         ]},
        {"tool": "complete_subgoal", "args": {"summary": "已读 a.sv"}},
        {"tool": "write_file",
         "args": {"path": "staging/rtl/a.sv",
                  "content": "module a; // fixed\nendmodule\n"}},
        {"tool": "run_shell",
         "args": {"command": [sys.executable, "-c", "print('ok')"]}},
        {"tool": "complete_subgoal",
         "args": {"summary": "写入并跑通命令"}},
        {"tool": "propose",
         "args": {"before": "baseline", "after": "fixed",
                  "reasoning_trace": "两个子目标都完成",
                  "open_questions": []}},
    ]
    harness = Harness(zones, config=HarnessConfig(decompose=True),
                      planner=_scripted(decisions))
    result = harness.run("补边界")

    assert result["status"] == "proposal"
    subs = harness.session.subgoals
    assert [s["id"] for s in subs] == ["G1", "G2"]
    assert all(s["status"] == "done" for s in subs)
    assert subs[0]["summary"] == "已读 a.sv"
    assert harness.session.goal["status"] == "completed"

    proposal = result["proposal"]
    assert len(proposal["evidence"]["subgoals"]) == 2
    from src.workspace.proposal.schema import Proposal
    stored = Proposal.load(zones, result["proposal_id"])
    gate = run_gate(stored, zones)
    assert gate["ok"] is True
    assert all(row["status"] != "fail" for row in gate["checks"]
               if row["name"] == "subgoals")


def test_blocked_subgoal_becomes_open_question(tmp_path):
    zones = _zones(tmp_path)
    decisions = [
        {"tool": "read_file", "args": {"path": "rtl/a.sv"},
         "subgoals": [
             {"id": "G1", "title": "读基线", "success": "知道实现"},
             {"id": "G2", "title": "改 RTL", "success": "跑通"},
         ]},
        {"tool": "block_subgoal", "args": {"reason": "缺少 DUT 编译环境"}},
        {"tool": "read_file", "args": {"path": "rtl/a.sv"}},
        {"tool": "run_shell",
         "args": {"command": [sys.executable, "-c", "print('ok')"]}},
        {"tool": "complete_subgoal", "args": {"summary": "已读 a.sv 并跑通命令"}},
        {"tool": "propose",
         "args": {"before": "baseline", "after": "partial",
                  "reasoning_trace": "G2 被阻塞", "open_questions": []}},
    ]
    harness = Harness(zones, config=HarnessConfig(decompose=True),
                      planner=_scripted(decisions))
    result = harness.run("补边界")

    assert result["status"] == "proposal"
    statuses = {s["id"]: s["status"] for s in harness.session.subgoals}
    assert statuses == {"G1": "blocked", "G2": "done"}
    assert "缺少 DUT 编译环境" in harness.session.working["open_questions"]
