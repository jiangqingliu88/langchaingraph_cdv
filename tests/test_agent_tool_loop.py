"""Bounded ReAct tool loop tests (no LLM key, no EDA)."""
from __future__ import annotations

import json

from src.layers.l2_orchestration.supervisor.tool_loop import run_tool_loop


class _Tool:
    def __init__(self, name, fn):
        self.name = name
        self.description = f"{name} tool"
        self._fn = fn
        self.calls = []

    def invoke(self, args):
        self.calls.append(dict(args))
        return self._fn(args)


def test_loop_calls_tool_then_final():
    read = _Tool("read_file", lambda a: f"contents:{a['path']}")
    replies = iter([
        json.dumps({"action": "tool", "tool": "read_file",
                    "args": {"path": "rtl/x.sv"}}),
        json.dumps({"action": "final", "answer": "fixed"}),
    ])
    result = run_tool_loop("fix rtl", [read], llm=lambda prompt: next(replies),
                           max_steps=3)
    assert result.ok is True
    assert result.answer == "fixed"
    assert result.steps == 2
    assert result.tool_calls[0].tool == "read_file"
    assert "rtl/x.sv" in read.calls[0].values()


def test_loop_rejects_unknown_tool_and_keeps_going():
    tool = _Tool("read_file", lambda a: "ok")
    replies = iter([
        json.dumps({"action": "tool", "tool": "rm_rf", "args": {}}),
        json.dumps({"action": "final", "answer": "done"}),
    ])
    result = run_tool_loop("x", [tool], llm=lambda prompt: next(replies))
    assert result.ok is True
    assert result.tool_calls == []          # 未知工具不执行
    assert result.answer == "done"


def test_loop_stops_at_max_steps():
    tool = _Tool("read_file", lambda a: "ok")
    result = run_tool_loop(
        "x", [tool],
        llm=lambda prompt: json.dumps(
            {"action": "tool", "tool": "read_file", "args": {}}),
        max_steps=2)
    assert result.ok is False
    assert result.steps == 2
    assert len(result.tool_calls) == 2
    assert "max_steps" in result.error


def test_loop_handles_llm_failure():
    result = run_tool_loop(
        "x", [_Tool("read_file", lambda a: "ok")],
        llm=lambda prompt: (_ for _ in ()).throw(RuntimeError("no key")))
    assert result.ok is False
    assert "no key" in result.error
