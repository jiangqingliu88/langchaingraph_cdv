"""PipelineState 字段契约 —— 谁写、谁读、是否 checkpoint。

`PHASE_OWNERS` 管“阶段产物唯一属主”；这里补关键流转字段（尤其是新加的
`sim_reward` / `knowledge_graph`）的写入者，并让运行期越权写入留痕。
"""
from __future__ import annotations

import asyncio

from src.layers.l2_orchestration import graph as graph_mod
from src.layers.l2_orchestration.graph import _guarded_node
from src.layers.l2_orchestration.state import (
    STATE_CONTRACTS,
    PipelineState,
    unexpected_state_writers,
)


def test_contracts_only_reference_existing_fields():
    assert set(STATE_CONTRACTS) <= set(PipelineState.model_fields)
    for field, contract in STATE_CONTRACTS.items():
        assert contract["writers"], f"{field} 没有写入者"
        assert contract["readers"], f"{field} 没有读者"
        assert "checkpoint" in contract


def test_new_cross_layer_fields_have_explicit_owners():
    assert STATE_CONTRACTS["sim_reward"]["writers"] == ("coverage",)
    assert STATE_CONTRACTS["knowledge_graph"]["writers"] == ("coverage",)
    assert "decide" in STATE_CONTRACTS["sim_reward"]["readers"]


def test_front_is_allowed_to_write_spec_and_arch():
    """front 是输入链入口，合法产出 spec/design_arch（不是越权）。"""
    assert unexpected_state_writers("front", {
        "spec": {}, "design_arch": {},
    }) == []


def test_owner_writing_its_own_field_is_fine():
    assert unexpected_state_writers("coverage", {
        "coverage": {}, "sim_reward": {}, "knowledge_graph": {},
    }) == []


def test_other_node_writing_a_contracted_field_is_flagged():
    assert unexpected_state_writers("design", {"coverage": {}}) == ["coverage"]
    assert unexpected_state_writers("ops", {"tests": {}}) == ["tests"]


def test_uncontracted_fields_stay_free():
    # phases / 计数器是多写者，不在契约表里 —— 不告警
    assert unexpected_state_writers("any_node", {"phases": [], "seed": 3}) == []


def test_warn_mode_reports_but_does_not_block(monkeypatch):
    """`SIGNOFFAI_STATE_CONTRACT=warn`：观察哨模式，不改变返回值。"""
    monkeypatch.setenv("SIGNOFFAI_STATE_CONTRACT", "warn")
    graph_mod._STATE_WARNED.clear()

    async def bad_node(state, config):
        return {"coverage": {"functional": 1.0}}

    wrapped = _guarded_node("design", bad_node)
    out = asyncio.run(wrapped({}, {}))
    assert out == {"coverage": {"functional": 1.0}}       # 不改变返回值
    assert ("design", "coverage") in graph_mod._STATE_WARNED
    assert getattr(wrapped, "__state_guard__", False) is True


def test_strict_mode_hard_fails_on_critical_field(monkeypatch):
    """关键字段（tests/coverage/audit/result）被越权写 → 硬失败，不是告警。"""
    monkeypatch.delenv("SIGNOFFAI_STATE_CONTRACT", raising=False)

    async def bad_node(state, config):
        return {"coverage": {"functional": 1.0}}

    wrapped = _guarded_node("design", bad_node)
    try:
        asyncio.run(wrapped({}, {}))
    except RuntimeError as exc:
        assert "State" in str(exc) or "state" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("关键字段越权写必须硬失败")


def test_strict_mode_still_warns_for_non_critical(monkeypatch):
    monkeypatch.delenv("SIGNOFFAI_STATE_CONTRACT", raising=False)
    graph_mod._STATE_WARNED.clear()

    async def bad_node(state, config):
        return {"gaps": {}}          # gaps 不是关键字段，只告警

    wrapped = _guarded_node("design", bad_node)
    assert asyncio.run(wrapped({}, {})) == {"gaps": {}}
    assert ("design", "gaps") in graph_mod._STATE_WARNED


def test_wrapper_is_idempotent():
    async def node(state, config):
        return {}

    once = _guarded_node("design", node)
    twice = _guarded_node("design", once)
    assert twice is once
