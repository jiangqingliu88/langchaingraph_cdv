"""`verified_by` 汇总规则 —— EDA 背书不能被 LLM 自述稀释。"""
from __future__ import annotations

from src.orchestration_plane.l2.communication.tool_protocol import (
    VERIFIED_BY_VALUES,
    aggregate_verified_by,
)


def test_all_eda_stays_eda():
    assert aggregate_verified_by(["eda", "eda"]) == "eda"


def test_mixed_is_explicit_not_eda():
    assert aggregate_verified_by(["eda", "llm"]) == "mixed"
    assert aggregate_verified_by(["llm", "eda", "none"]) == "mixed"


def test_llm_only_stays_llm():
    assert aggregate_verified_by(["llm", "llm"]) == "llm"


def test_none_only_is_none():
    assert aggregate_verified_by(["none", "", None]) == "none"
    assert aggregate_verified_by([]) == "none"


def test_aggregate_values_are_declared():
    assert set(VERIFIED_BY_VALUES) == {"eda", "llm", "none", "mixed"}
