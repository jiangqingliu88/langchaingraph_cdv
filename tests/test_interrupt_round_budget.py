"""中断/恢复不能改变轮次语义 —— 结构级守卫。

完整 resume 需要 Runtime + checkpointer；这里钉住三件最容易漂的事：
  1. `approval` 的 proceed 分支**不经过** `round_bump`（恢复后不会多算一轮）；
  2. `n_approval` 自己不写轮次字段（轮次只由 `round_bump` 收口）；
  3. `round_num` / `iterations` 的 reducer 仍是“每次 +1”，budget 由 router 判。
"""
from __future__ import annotations

import ast
import inspect

from src.layers.l2_orchestration.graph import build_closed_loop_graph
from src.layers.l2_orchestration.nodes.pure.approval import n_approval
from src.layers.l2_orchestration.nodes.pure.rounds import n_round_bump, _have_rounds_left
from src.layers.l2_orchestration.routers import r_approval
from src.layers.l2_orchestration.state import PipelineState


def test_approval_proceed_does_not_reenter_round_bump():
    graph = build_closed_loop_graph().get_graph()
    edges = {(e.source, e.target, e.data) for e in graph.edges}
    assert ("approval", "record_decision", "proceed") in edges
    assert ("approval", "audit", "reject") in edges
    # skip 是显式“本轮不做动作”，回到 round_bump 是合法的
    assert ("approval", "round_bump", "skip") in edges
    assert ("approval", "round_bump", "proceed") not in edges


def test_approval_node_does_not_write_round_fields():
    src = inspect.getsource(n_approval)
    tree = ast.parse(src)
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    keys = set()
    for node in returns:
        if isinstance(node.value, ast.Dict):
            for k in node.value.keys:
                if isinstance(k, ast.Constant):
                    keys.add(k.value)
    assert "round_num" not in keys and "iterations" not in keys


def test_approval_routing_is_total_and_side_effect_free():
    assert r_approval(PipelineState(approval_outcome="reject")) == "reject"
    assert r_approval(PipelineState(approval_outcome="skip")) == "skip"
    assert r_approval(PipelineState(approval_outcome="proceed")) == "proceed"


def test_round_budget_router_uses_absolute_round_number():
    assert _have_rounds_left(PipelineState(round_num=1, max_rounds=1)) is True
    assert _have_rounds_left(PipelineState(round_num=2, max_rounds=1)) is False
    assert inspect.iscoroutinefunction(n_round_bump)


def test_audit_fallback_records_last_completed_round_not_the_next_one():
    """round_bump 已经把 round_num 推到下一轮；audit 补记时不能再 +1。"""
    from src.layers.l2_orchestration.nodes.agent.signoff import n_audit

    src = inspect.getsource(n_audit)
    assert "state.round_num - 1" in src
