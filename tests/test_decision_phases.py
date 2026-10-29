"""决策引擎的两阶段边界 —— **硬失败规则先，软建议后**。

这不是命名偏好：硬失败（编译/比对/功能回归）一旦被软策略覆盖，闭环就会
去"补测试"而不是"修真正坏掉的东西"。这里用测试把结构钉住。
"""
from __future__ import annotations

from src.layers.l3_decision.brain.decision_brain import DecisionBrain
from src.layers.l3_decision.decision_engine import (
    Action,
    CoverageDrivenDecisionEngine,
    Observation,
)


def _hard_obs() -> Observation:
    return Observation(
        compile_error={"error_type": "syntax", "message": "bad"},
        coverage={"functional": 10.0},
        gaps=[{"reason": "unstimulated"}],
    )


def _soft_obs() -> Observation:
    return Observation(
        coverage={"functional": 50.0},
        gaps=[{"reason": "unstimulated", "bin": "x"}],
    )


def test_hard_failure_wins_over_soft_suggestions():
    action = CoverageDrivenDecisionEngine(target=95).decide(_hard_obs())
    assert action.action_type == "FIX_COMPILE_bug"
    assert action.source == "rule_hard"


def test_hard_action_returns_none_when_nothing_is_broken():
    engine = CoverageDrivenDecisionEngine(target=95)
    assert engine.hard_action(_soft_obs()) is None
    assert engine.soft_action(_soft_obs()).action_type == "GENERATE_DIRECTED_TEST"


def test_soft_actions_are_tagged_rule_and_converge_is_terminal():
    engine = CoverageDrivenDecisionEngine(target=95)
    assert engine.soft_action(_soft_obs()).source == "rule"
    done = engine.soft_action(Observation(coverage={"functional": 99.0}))
    assert done.action_type == "CONVERGE"
    assert done.source == "terminal"


def test_decide_is_exactly_hard_then_soft():
    engine = CoverageDrivenDecisionEngine(target=95)
    assert engine.decide(_hard_obs()).action_type == engine.hard_action(_hard_obs()).action_type
    assert engine.decide(_soft_obs()).action_type == engine.soft_action(_soft_obs()).action_type


class _NoRl:
    """RL 一旦被调用就失败 —— 用来证明硬阶段根本没走到软阶段。"""

    def has_experience(self, state):
        raise AssertionError("硬失败路径不该读 RL 经验")

    def select_action(self, state):
        raise AssertionError("硬失败路径不该让 RL 选动作")

    def learn(self, *a, **k):
        pass

    def q_entries_for(self, state):
        return 0

    def stats(self):
        return {}


def test_brain_never_consults_rl_for_hard_failures():
    brain = DecisionBrain(CoverageDrivenDecisionEngine(target=95), _NoRl(), target=95)
    action = brain.decide(_hard_obs())
    assert action.action_type == "FIX_COMPILE_bug"
    assert action.source == "rule_hard"


class _ColdRl:
    def has_experience(self, state):
        return False

    def select_action(self, state):
        raise AssertionError("冷启动不该让 RL 选动作")

    def learn(self, *a, **k):
        pass

    def q_entries_for(self, state):
        return 0

    def stats(self):
        return {}


def test_brain_soft_phase_uses_soft_action(monkeypatch):
    engine = CoverageDrivenDecisionEngine(target=95)
    calls = []

    def fake_soft(obs):
        calls.append(obs)
        return Action(action_type="EXPAND_SEEDS", reason="soft-only")

    monkeypatch.setattr(engine, "soft_action", fake_soft)
    brain = DecisionBrain(engine, _ColdRl(), target=95)
    action = brain.decide(_soft_obs())
    assert action.action_type == "EXPAND_SEEDS"
    assert action.source == "rule"
    assert calls and calls[0].coverage["functional"] == 50.0
