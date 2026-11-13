"""agent_service：直接模式 turn、退出码、无 proposal、run_stage 接线。"""
from __future__ import annotations

import json

from src.interfaces.api import agent_mode_service as agent_service


def _planner(*steps):
    queue = list(steps)

    def plan(payload):
        return json.dumps(queue.pop(0))
    return plan


def test_agent_turn_writes_in_place_and_skips_proposal(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    planner = _planner(
        {"tool": "list_files", "args": {"path": "."}},
        {"tool": "write_file", "args": {"path": "b.txt", "content": "world\n"}},
        {"tool": "finish", "args": {"summary": "wrote b.txt"}},
    )
    result = agent_service.agent_turn("make b", workspace=str(tmp_path),
                                      planner=planner, max_steps=10)
    assert result["status"] == "finished_no_proposal"
    assert result["exit_code"] == 0
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "world\n"
    assert not list((tmp_path / ".signoffai" / "proposals").glob("*.json"))

    session = json.loads(
        (tmp_path / ".signoffai" / "sessions" /
         f"{result['session_id']}.json").read_text(encoding="utf-8"))
    assert session["messages"][0]["role"] == "user"
    assert session["messages"][0]["content"] == "make b"


def test_agent_turn_is_multi_turn(tmp_path):
    planner = _planner({"tool": "finish", "args": {"summary": "first"}})
    first = agent_service.agent_turn("first", workspace=str(tmp_path),
                                     planner=planner)
    second = agent_service.agent_turn(
        "second", workspace=str(tmp_path), planner=_planner(
            {"tool": "finish", "args": {"summary": "second"}}),
        session_id=first["session_id"])
    assert first["session_id"] == second["session_id"]
    assert second["summary"] == "second"


def test_bad_decisions_block_with_nonzero_exit(tmp_path):
    def broken(payload):
        return json.dumps({"tool": "no_such_tool", "args": {}})

    result = agent_service.agent_turn("x", workspace=str(tmp_path),
                                      planner=broken, max_steps=10)
    assert result["status"] == "blocked"
    assert result["exit_code"] == 1


def test_run_stage_uses_injected_runner(tmp_path):
    calls = []

    def runner(role, **kwargs):
        calls.append((role, str(kwargs.get("output_dir"))))
        return {"ok": True, "success": True, "data": {"output": "ok"}}

    planner = _planner(
        {"tool": "run_stage",
         "args": {"role": "design", "run": ".signoffai/runs/d1"}},
        {"tool": "finish", "args": {"summary": "done"}},
    )
    result = agent_service.agent_turn("design it", workspace=str(tmp_path),
                                      planner=planner, stage_runner=runner)
    assert result["exit_code"] == 0
    assert calls and calls[0][0] == "design"
    assert calls[0][1].replace("\\", "/").endswith(".signoffai/runs/d1")
    assert result["session"]["runs"][0]["role"] == "design"
