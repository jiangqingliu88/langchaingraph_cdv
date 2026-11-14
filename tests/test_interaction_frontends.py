"""三个前端的 Agent/Engine 共享与审批边界。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.workbench.api import agent_mode_service
from src.workbench.modes.interaction import model_configuration_label, pending_text, resume, turn


def test_chat_uses_agent_turn_with_multi_turn_and_execution_approval():
    received = []

    def spy(prompt, **kwargs):
        received.append((prompt, kwargs))
        return {"status": "proposal", "summary": "候选回答", "session_id": "session-1"}

    reply = turn("解释握手", workspace="demo", frontend="gui", agent_caller=spy)
    assert received[0][1]["session_id"] is None
    assert received[0][1]["config"] == {"require_exec_approval": True}
    assert "frontend" not in received[0][1]
    assert reply["interaction"] == {"mode": "chat", "frontend": "gui"}
    assert reply["human_review_required"] is True
    turn("继续解释", session_id="session-1", agent_caller=spy)
    assert received[1][1]["session_id"] == "session-1"
    assert "PROTOCOL_TOOL_SCHEMA" not in reply


def test_plan_has_real_checkpoint_not_fence_or_generated_pass():
    seen = {}

    def fake_agent(prompt, **kwargs):
        seen.update(kwargs)
        return {
            "status": "paused",
            "session_id": "s",
            "session": {"session_id": "s"},
            "pending": {"kind": "plan", "plan": "候选计划"},
        }

    reply = turn("规划一个验证任务", mode="plan", agent_caller=fake_agent)
    assert seen["config"]["require_plan_approval"] is True
    assert seen["config"]["plan_first"] is True
    assert reply["status"] == "paused"
    assert reply["session_id"] == "s"
    assert reply["human_review_required"] is True
    assert pending_text(reply).startswith("请审查候选计划")


def test_only_explicit_verify_enters_engine():
    seen = {}

    def fake_verify(goal, **kwargs):
        seen.update(kwargs)
        return {"mode": "verify", "status": "INCOMPLETE", "reason": "EDA 不可用"}

    reply = turn("运行指定验证任务", mode="verify", verifier_caller=fake_verify)
    assert seen == {"mode": "verify"}
    assert reply["status"] == "INCOMPLETE"
    assert reply["reason"] == "EDA 不可用"
    assert reply["interaction"]["mode"] == "verify"


def test_empty_and_unknown_modes_do_not_invoke_model():
    invoked = []
    reply = turn("", agent_caller=lambda *_a, **_k: invoked.append(1))
    assert reply["status"] == "invalid"
    assert reply["exit_code"] == 1
    assert not invoked
    with pytest.raises(ValueError, match="未知交互模式"):
        turn("任意目标", mode="guess", agent_caller=lambda *_a, **_k: {})
    assert not invoked


def test_resume_uses_the_real_harness_resume_api(monkeypatch):
    seen = {}

    def fake_resume(session_id, **kwargs):
        seen.update(kwargs)
        return {"status": "paused", "session_id": session_id, "pending": {"kind": "approval", "reason": "真实审批待决"}}

    monkeypatch.setattr(agent_mode_service, "resume_turn", fake_resume)
    reply = resume("sid", workspace="w", approve=False, frontend="gui")
    assert seen["workspace"] == "w"
    assert seen["approve"] is False
    assert seen["answer"] == ""
    assert "审批" in pending_text(reply)


def test_model_configuration_label_reports_missing_key_without_showing_secret(monkeypatch):
    from config.settings import Settings

    monkeypatch.setattr(
        Settings,
        "get_instance",
        lambda: SimpleNamespace(llm=SimpleNamespace(api_key="", provider="deepseek", model="deepseek-flash")),
    )
    assert "LLM_API_KEY 未设置" in model_configuration_label()

    monkeypatch.setattr(
        Settings,
        "get_instance",
        lambda: SimpleNamespace(
            llm=SimpleNamespace(api_key="DO_NOT_SHOW_TEST_VALUE", provider="local", model="echo-model")
        ),
    )
    label = model_configuration_label()
    assert "local/echo-model" in label
    assert "未测连通" in label
    assert "DO_NOT_SHOW_TEST_VALUE" not in label
