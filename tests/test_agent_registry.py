"""Agent card / skill policy / StageTool tests (no LLM, no EDA)."""
from __future__ import annotations

import json

import pytest

from src.engine.orchestration.registry import AGENT_CARDS, card, validate_registry
from src.agent.runtime import stage_tools
from src.engine.orchestration.stage_policy import (
    StagePolicyError, assert_stage, assert_tool, can_call_stage,
    should_ask_human,
)


def test_agent_registry_matches_real_skill_dirs():
    assert validate_registry() == []
    assert card("design").max_attempts == 2
    assert card("debug").requires_human_after == 5


def test_skill_policy_blocks_unlisted_skills():
    assert can_call_stage("design", "design") is True
    assert can_call_stage("design", "audit") is False
    with pytest.raises(StagePolicyError):
        assert_stage("design", "audit")
    with pytest.raises(StagePolicyError):
        assert_tool("coverage", "auto_fix")


def test_human_review_threshold_comes_from_card():
    assert should_ask_human("debug", 4) is False
    assert should_ask_human("debug", 5) is True
    assert should_ask_human("design", 99) is False


def test_skill_tool_returns_structured_summary(monkeypatch):
    async def fake_run_agent(rt, state, role, label, params):
        return ({"ok": True, "role": role, "params": params},
                {"name": label, "status": "passed"})

    monkeypatch.setattr(stage_tools, "_run_agent", fake_run_agent)
    tool = stage_tools.StageTool("design", "design", rt=object(), state=object())
    out = json.loads(tool.invoke({"params": {"style": "x"}}))
    assert out["stage"] == "design"
    assert out["data"]["role"] == "design"
    assert out["phase"]["status"] == "passed"

    tools = stage_tools.build_stage_tools(object(), object(), "design")
    assert [t.name for t in tools] == [
        "run_front_stage", "run_design_stage", "run_model_stage"]
