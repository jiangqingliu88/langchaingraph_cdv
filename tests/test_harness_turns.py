"""长循环 harness：任务注入、多轮 send、决策 schema。"""
from __future__ import annotations

import json

import jsonschema

from src.agent.runtime.context import prompt_messages
from src.agent.runtime.harness import (
    DECISION_SCHEMA,
    Harness,
    HarnessConfig,
)
from src.runtime.session import Session
from src.runtime.workspace_manager import WorkspaceZones


def _finisher(payload):
    return json.dumps({"tool": "finish", "args": {"summary": payload["task"]}})


def _harness(tmp_path, planner=None, **cfg):
    zones = WorkspaceZones.direct_mode(tmp_path)
    config = HarnessConfig(emit_proposal=False, project_root=str(tmp_path), **cfg)
    return Harness(zones, config=config, planner=planner)


def test_task_is_injected_as_user_message(tmp_path):
    harness = _harness(tmp_path, planner=_finisher)
    result = harness.run("inspect rtl")
    assert result["status"] == "finished_no_proposal"
    assert harness.session.messages[0]["role"] == "user"
    assert harness.session.messages[0]["content"] == "inspect rtl"


def test_send_starts_a_second_turn_on_same_session(tmp_path):
    harness = _harness(tmp_path, planner=_finisher)
    first = harness.run("first")
    harness = Harness(harness.zones,
                      config=HarnessConfig(emit_proposal=False,
                                           project_root=str(tmp_path)),
                      planner=_finisher,
                      session_id=first["session"]["session_id"])
    second = harness.send("second")
    assert second["status"] == "finished_no_proposal"
    user_turns = [m for m in harness.session.messages if m.get("role") == "user"]
    assert [m["content"] for m in user_turns] == ["first", "second"]
    assert harness.session.earlier_turns[0]["task"] == "first"


def test_send_while_paused_asks_for_resume(tmp_path):
    def asker(payload):
        return json.dumps({"tool": "ask_user",
                           "args": {"question": "which?"}})

    harness = _harness(tmp_path, planner=asker)
    assert harness.run("task")["status"] == "paused"
    assert harness.send("next")["status"] == "paused"


def test_decision_schema_accepts_subgoals():
    doc = {
        "thought": "plan",
        "plan": "split it",
        "subgoals": [{"id": "G1", "title": "a", "success": "done"}],
        "tool": "finish",
        "args": {"summary": "ok"},
    }
    jsonschema.validate(doc, DECISION_SCHEMA)


def test_transcript_flattens_native_tool_calls(tmp_path):
    session = Session(session_id="H-test", task="t")
    session.append("user", "t")
    session.append("assistant", "thinking", tool_calls=[{
        "id": "c1", "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"a"}'}}])
    session.append("tool", "content", name="read_file", tool_call_id="c1",
                   args={"path": "a"})
    messages = prompt_messages(session, "system")
    assert messages[0]["role"] == "system"
    assert all("tool_calls" not in m for m in messages)
    assert messages[1] == {"role": "user", "content": "t"}
    assert messages[2] == {"role": "assistant", "content": "thinking"}
    assert messages[3]["role"] == "user"
    assert messages[3]["content"].startswith("[observation:read_file args=")
