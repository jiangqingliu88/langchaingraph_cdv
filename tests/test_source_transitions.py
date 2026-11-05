"""动作来源契约 —— `source` 是 L5 蒸馏的取样本依据，不能想标就标。"""
from __future__ import annotations

from src.layers.l3_decision.decision_engine import (
    SOURCE_VALUES,
    Action,
    validate_action_source,
)


def test_all_known_sources_are_declared():
    assert SOURCE_VALUES == ("rule_hard", "rule", "rl_suggested",
                             "rl_overridden", "terminal")


def test_hard_failures_are_rule_hard_only():
    for action_type in ("FIX_COMPILE_bug", "FIX_MODEL_bug",
                        "FIX_FUNCTIONAL_bug", "FIX_PROTOCOL_bug",
                        "FIX_RESET_bug", "FIX_CDC_bug", "FIX_DEADCODE_bug"):
        assert validate_action_source(Action(action_type, source="rule_hard")) == []
    assert validate_action_source(
        Action("RELAX_CONSTRAINT", source="rule_hard"))


def test_terminal_only_for_converge():
    assert validate_action_source(Action("CONVERGE", source="terminal")) == []
    assert validate_action_source(
        Action("GENERATE_DIRECTED_TEST", source="terminal"))
    assert validate_action_source(
        Action("CONVERGE", source="rl_suggested"))


def test_rl_cannot_claim_hard_or_terminal_actions():
    for source in ("rl_suggested", "rl_overridden"):
        assert validate_action_source(Action("GENERATE_DIRECTED_TEST", source=source)) == []
        assert validate_action_source(Action("FIX_COMPILE_bug", source=source))
        assert validate_action_source(Action("CONVERGE", source=source))


def test_unknown_source_is_rejected():
    assert validate_action_source(Action("EXPAND_SEEDS", source="magic"))
    assert validate_action_source(None) == []
