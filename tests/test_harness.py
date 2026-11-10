"""Harness：状态机 / 回填 / 计划审批 / 命令审批 / ask_user / 压缩 / rounds / 子 agent。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from src.workspace import WorkspaceZones
from src.workspace.harness import Harness, HarnessConfig, HarnessState, StateMachine
from src.workspace.harness.context import Compactor, estimate_messages
from src.workspace.harness.jobs import JobManager
from src.workspace.harness.session import Session
from src.workspace.harness.skills import SkillLibrary
from src.workspace.harness.state import StateTransitionError
from src.workspace.harness.subagent import run_subagent


def _zones(tmp_path: Path) -> WorkspaceZones:
    src = tmp_path / "baseline"
    (src / "rtl").mkdir(parents=True)
    (src / "rtl" / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    return WorkspaceZones.init(tmp_path / "ws", src)


def _scripted(decisions):
    queue = list(decisions)

    def planner(payload):
        return queue.pop(0)

    return planner


def _proposal_args(**over):
    args = {"before": "module a; endmodule", "after": "fixed",
            "reasoning_trace": "read then write", "open_questions": []}
    args.update(over)
    return args


def _normal_steps():
    return [
        {"thought": "读", "tool": "read_file", "args": {"path": "rtl/a.sv"}},
        {"thought": "写", "tool": "write_file",
         "args": {"path": "staging/rtl/a.sv",
                  "content": "module a; // fixed\nendmodule\n"}},
        {"thought": "跑", "tool": "run_shell",
         "args": {"command": [sys.executable, "-c", "print('ok')"]}},
        {"thought": "交", "tool": "propose", "args": _proposal_args()},
    ]


def test_state_machine_rejects_illegal_transition():
    machine = StateMachine()
    machine.transition(HarnessState.PLANNING)
    machine.transition(HarnessState.DONE)
    with pytest.raises(StateTransitionError):
        machine.transition(HarnessState.PLANNING)


def test_full_run_backfills_messages_and_evidence(tmp_path):
    zones = _zones(tmp_path)
    harness = Harness(zones, planner=_scripted(_normal_steps()))
    result = harness.run("补一个边界用例")

    assert result["status"] == "proposal"
    session = harness.session
    assert session.state == "done"
    assert session.goal["status"] == "completed"
    roles = [m["role"] for m in session.messages]
    assert roles.count("assistant") >= 4
    assert roles.count("tool") >= 3
    tool_messages = [m for m in session.messages if m["role"] == "tool"]
    assert all(m["tool_call_id"] for m in tool_messages)
    assert session.working["changed_files"][0]["path"] == "staging/rtl/a.sv"
    assert session.working["evidence"]["commands"][0]["exit_code"] == 0
    saved = json.loads((zones.session_path(session.session_id)).read_text(encoding="utf-8"))
    assert saved["state"] == "done"
    events = [json.loads(line) for line in
              (zones.harness_dir / "sessions" / f"{session.session_id}.events.jsonl")
              .read_text(encoding="utf-8").splitlines()]
    kinds = {row["kind"] for row in events}
    assert {"state", "decision", "tool.call", "tool.result", "proposal"} <= kinds


def test_plan_first_does_not_execute_without_plan(tmp_path):
    zones = _zones(tmp_path)
    decisions = [
        {"tool": "write_file",
         "args": {"path": "staging/rtl/early.sv", "content": "module early; endmodule\n"}},
        {"plan": "先计划", "tool": "read_file", "args": {"path": "rtl/a.sv"}},
        *_normal_steps()[1:],
    ]
    harness = Harness(zones, config=HarnessConfig(plan_first=True),
                      planner=_scripted(decisions))
    result = harness.run("补边界")
    assert result["status"] == "proposal"
    # 第一条没有 plan 的工具调用没有被执行
    assert not (zones.staging / "rtl" / "early.sv").exists()


def test_plan_approval_pauses_and_resumes_from_disk(tmp_path):
    zones = _zones(tmp_path)
    config = HarnessConfig(plan_first=True, require_plan_approval=True)
    decisions = [{"thought": "先计划", "plan": "先读再改", "tool": "read_file",
                  "args": {"path": "rtl/a.sv"}}] + _normal_steps()
    first = Harness(zones, config=config, planner=_scripted(decisions))
    paused = first.run("补边界")
    assert paused["status"] == "paused"
    assert paused["session"]["state"] == "awaiting_plan"
    assert first.session.plan == "先读再改"

    second = Harness(zones, config=config, planner=_scripted(decisions[1:]),
                     session_id=first.session.session_id)
    result = second.resume(approve=True)
    assert result["status"] == "proposal"
    assert second.session.plan_approved is True


def test_exec_approval_pauses_and_resumes(tmp_path):
    zones = _zones(tmp_path)
    config = HarnessConfig(require_exec_approval=True)
    harness = Harness(zones, config=config, planner=_scripted([
        {"tool": "run_shell",
         "args": {"command": [sys.executable, "-c", "print('ok')"]}},
        {"tool": "propose", "args": _proposal_args()},
    ]))
    paused = harness.run("跑命令")
    assert paused["status"] == "paused"
    assert paused["pending"]["kind"] == "approval"

    result = harness.resume(approve=True)
    assert result["status"] == "proposal"
    assert harness.session.working["evidence"]["commands"][0]["exit_code"] == 0


def test_ask_user_pauses_and_resumes(tmp_path):
    zones = _zones(tmp_path)
    harness = Harness(zones, planner=_scripted([
        {"tool": "ask_user", "args": {"question": "用哪种边界？"}},
        *_normal_steps(),
    ]))
    paused = harness.run("补边界")
    assert paused["status"] == "paused"
    assert paused["pending"]["kind"] == "answer"

    result = harness.resume(answer="用 0x7f")
    assert result["status"] == "proposal"
    assert any(m.get("role") == "user" and "0x7f" in str(m.get("content"))
               for m in harness.session.messages)


def test_compactor_prunes_large_tool_results():
    session = Session(session_id="H-test", task="t")
    session.append("system", "sys")
    for i in range(10):
        session.append("tool", "x" * 5000, tool_call_id=f"c{i}", name="read_file")
    assert estimate_messages(session.messages) > 1000
    compactor = Compactor(max_tokens=1000)
    assert compactor.maybe_compact(session) is True
    assert session.compactions == 1
    assert any(message.get("pruned") for message in session.messages)


def test_invalid_proposal_triggers_next_round(tmp_path):
    zones = _zones(tmp_path)
    decisions = [
        {"tool": "propose", "args": _proposal_args()},   # 没有命令证据 → 不合法
        *_normal_steps(),
    ]
    harness = Harness(zones, config=HarnessConfig(max_rounds=2),
                      planner=_scripted(decisions))
    result = harness.run("补边界")
    assert result["status"] == "proposal"
    rounds = harness.session.goal["rounds"]
    assert len(rounds) == 2
    assert rounds[0]["state"] == "invalid"


def test_skills_are_discovered_and_readable(tmp_path):
    zones = _zones(tmp_path)
    skills_dir = zones.root / ".skills"
    skills_dir.mkdir()
    (skills_dir / "review.md").write_text(
        "---\nname: review\ndescription: 代码评审\n---\n先看 diff。\n",
        encoding="utf-8")
    library = SkillLibrary(zones)
    assert library.names() == ["review"]
    assert "先看 diff" in library.read("review")
    assert "review" in library.prompt_section()


def test_jobs_start_output_and_status(tmp_path):
    zones = _zones(tmp_path)
    manager = JobManager(zones)
    job = manager.start([sys.executable, "-c", "print('job-ok')"], name="smoke")
    for _ in range(100):
        status = manager.status(job["job_id"])
        if status["status"] == "exited":
            break
        time.sleep(0.05)
    assert status["exit_code"] == 0
    assert "job-ok" in manager.output(job["job_id"])["output"]


def test_subagent_is_bounded_and_does_not_emit_proposal(tmp_path):
    zones = _zones(tmp_path)
    child_decisions = [
        {"tool": "write_file",
         "args": {"path": "staging/rtl/child.sv", "content": "module child; endmodule\n"}},
        {"tool": "run_shell",
         "args": {"command": [sys.executable, "-c", "print('child')"]}},
        {"tool": "propose", "args": _proposal_args()},
    ]
    parent = Harness(zones, planner=_scripted(child_decisions))
    result = run_subagent(parent, "child task", max_steps=5)
    assert result["ok"] is True
    assert result["session_id"]
    assert (zones.staging / "rtl" / "child.sv").is_file()
    assert not list(zones.proposals.glob("*.json"))
