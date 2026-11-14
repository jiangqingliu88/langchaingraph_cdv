"""GUI 对话的 9 种 Agent 模式：清单 + 后端接线。

平台只有三条真交互路径（chat/plan/verify）；9 种模式是领域角色，
必须把 role_prompt / 交互方式真实传给后端，而不是只改界面文字。
"""

from __future__ import annotations

from src.workbench.modes.agent_modes import AGENT_MODES, get_mode, mode_ids
from src.workbench.modes.interaction import turn

EXPECTED = [
    ("agentic_chat", "Agentic Chat", "General-purpose chat for workspace exploration and code assistance"),
    ("mental_model", "Mental Model", "Design understanding and analysis mode"),
    ("formal", "Formal", "Formal verification agent mode"),
    ("uvm", "UVM", "UVM testplan, testbench development mode"),
    ("rtl_designer", "RTL Designer", "Lint violation Auto-fix"),
    ("unit_testing", "Unit Testing Agent", "Unit testing and testbench development (SV based, no UVM)"),
    (
        "functional_coverage",
        "Functional Coverage (interface-based)",
        "Functional coverage monitor generation (RTL interface-based)",
    ),
    ("debug", "Debug", "DV debug agent mode"),
    ("workflows", "Workflows", "End-to-end automated workflows"),
]


def test_registry_matches_the_nine_modes():
    assert [(m.id, m.label, m.description) for m in AGENT_MODES] == EXPECTED
    assert len(set(mode_ids())) == 9
    assert all(m.interaction in ("chat", "plan", "verify") for m in AGENT_MODES)


def test_unknown_mode_falls_back_to_agentic_chat():
    assert get_mode("no-such-mode").id == "agentic_chat"
    assert get_mode(None).id == "agentic_chat"


def test_plan_mode_passes_role_prompt_and_approval_flags():
    seen = {}

    def fake_agent(prompt, **kwargs):
        seen.update(kwargs)
        return {"status": "ok", "summary": "planned"}

    out = turn("设计 UVM testplan", mode="plan", agent_mode="uvm", agent_caller=fake_agent, frontend="gui")
    cfg = seen["config"]
    assert cfg["plan_first"] is True
    assert cfg["require_plan_approval"] is True
    assert "UVM" in cfg["role_prompt"]
    assert out["interaction"]["agent_mode"] == "uvm"
    assert out["interaction"]["mode"] == "plan"


def test_mental_model_mode_keeps_chat_but_has_role_prompt():
    seen = {}

    def fake_agent(prompt, **kwargs):
        seen.update(kwargs)
        return {"status": "ok"}

    turn("分析这份设计", mode="chat", agent_mode="mental_model", agent_caller=fake_agent)
    cfg = seen["config"]
    assert "plan_first" not in cfg
    assert "Mental Model" in cfg["role_prompt"]


def test_workflows_uses_verify_router():
    seen = {}

    def fake_verify(prompt, **kwargs):
        seen.update(kwargs)
        return {"status": "ok", "summary": "verify"}

    out = turn("跑一遍闭环", mode="verify", agent_mode="workflows", verifier_caller=fake_verify)
    assert seen["mode"] == "verify"
    assert out["interaction"]["agent_mode"] == "workflows"
