"""专家子图 —— 主图只挂 4 个专家，不直接铺 24 个节点。

    design_expert     front → design → model
    verify_expert     verify → env_arch_check
    debug_expert      round_bump → ops → debug_functional（失败才回环）
    coverage_expert   coverage → decide → governor → approval → 动作

`debug_expert` 是有环子图：回归失败 → debug → 下一轮 → 再跑 ops，直到通过
或轮次预算用尽。`coverage_expert` 把“覆盖率报告 → 决策 → 动作”收在一个子图；
动作不是 CONVERGE 时只标记“需要下一轮”，由主图重新派给 debug_expert。
"""
from __future__ import annotations

from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.layers.l2_orchestration.nodes.agent.build import (
    n_design, n_front, n_model, n_verify,
)
from src.layers.l2_orchestration.nodes.agent.fix import (
    n_apply_compile_retry, n_apply_directed_test, n_apply_update_model,
    n_refactor_rtl,
)
from src.layers.l2_orchestration.nodes.agent.run import (
    n_coverage, n_debug_functional, n_ops,
)
from src.layers.l2_orchestration.nodes.pure.apply import (
    n_apply_converge, n_apply_expand_seeds, n_apply_relax,
)
from src.layers.l2_orchestration.nodes.pure.approval import n_approval
from src.layers.l2_orchestration.nodes.pure.converge import (
    n_decide, n_governor, n_governor_retry, n_record_decision,
)
from src.layers.l2_orchestration.nodes.pure.rounds import (
    n_env_arch_check, n_round_bump,
)
from src.layers.l2_orchestration.routers import (
    r_action, r_after_compile_retry, r_after_converge, r_after_design,
    r_after_guardian, r_after_round_bump, r_approval, r_coverage, r_governor,
)
from src.layers.l2_orchestration.state import PipelineState


def _marker(**updates: Any):
    """一个只写标记字段的 async 节点。"""
    async def _node(state, config):
        return dict(updates)
    return _node


def build_design_subgraph():
    """设计专家：前置分析 → design → model。"""
    g = StateGraph(PipelineState)
    g.add_node("front", n_front)
    g.add_node("design", n_design)
    g.add_node("model", n_model)
    g.add_node("mark_design_done", _marker(design_done=True))
    g.add_edge(START, "front")
    g.add_edge("front", "design")
    g.add_conditional_edges("design", r_after_design, {
        "ok": "model",
        "abort": "mark_design_done",
    })
    g.add_edge("model", "mark_design_done")
    g.add_edge("mark_design_done", END)
    return g.compile()


def build_verify_subgraph():
    """验证专家：verify（UVM/用例/IR）→ env 架构检查。"""
    g = StateGraph(PipelineState)
    g.add_node("verify", n_verify)
    g.add_node("env_arch_check", n_env_arch_check)
    g.add_node("mark_verify_done", _marker(verify_done=True))
    g.add_edge(START, "verify")
    g.add_edge("verify", "env_arch_check")
    g.add_edge("env_arch_check", "mark_verify_done")
    g.add_edge("mark_verify_done", END)
    return g.compile()


def build_debug_subgraph():
    """执行/调试专家：轮次 → ops → 失败才进 debug，然后回到下一轮。"""
    g = StateGraph(PipelineState)
    for name, fn in (
        ("round_bump", n_round_bump),
        ("ops", n_ops),
        ("debug_functional", n_debug_functional),
    ):
        g.add_node(name, fn)
    g.add_node("mark_debug_done", _marker(debug_done=True))
    g.add_node("mark_execution_done", _marker(execution_done=True))
    g.add_edge(START, "round_bump")
    g.add_conditional_edges("round_bump", r_after_round_bump, {
        "next_round": "ops",
        "give_up": "mark_execution_done",
    })
    g.add_conditional_edges("ops", r_coverage, {
        "eda_missing": "mark_execution_done",
        "awaiting_approval": "mark_execution_done",
        "compile_fail": "debug_functional",
        "functional_fail": "debug_functional",
        "run_coverage": "mark_debug_done",
    })
    g.add_edge("debug_functional", "round_bump")
    g.add_edge("mark_debug_done", END)
    g.add_edge("mark_execution_done", END)
    return g.compile()


def build_coverage_subgraph():
    """覆盖率专家：coverage → decide → governor → approval → 动作。

    非 CONVERGE 动作只写 `mark_round_needed`（清掉 debug/coverage 完成标记），
    由主图重新派 debug_expert；不在本子图里直接跑下一轮 ops。
    """
    g = StateGraph(PipelineState)
    for name, fn in (
        ("coverage", n_coverage),
        ("decide", n_decide),
        ("governor", n_governor),
        ("governor_retry", n_governor_retry),
        ("approval", n_approval),
        ("record_decision", n_record_decision),
        ("apply_converge", n_apply_converge),
        ("apply_compile_retry", n_apply_compile_retry),
        ("refactor_rtl", n_refactor_rtl),
        ("apply_update_model", n_apply_update_model),
        ("apply_directed_test", n_apply_directed_test),
        ("apply_relax", n_apply_relax),
        ("apply_expand_seeds", n_apply_expand_seeds),
    ):
        g.add_node(name, fn)
    g.add_node("mark_round_needed", _marker(
        debug_done=False, coverage_done=False, execution_done=False))
    g.add_node("mark_execution_done", _marker(
        execution_done=True, coverage_done=True))

    g.add_edge(START, "coverage")
    g.add_edge("coverage", "decide")
    g.add_edge("decide", "governor")
    g.add_conditional_edges("governor", r_governor, {
        "proceed": "approval",
        "retry": "governor_retry",
        "abort": "mark_execution_done",
    })
    g.add_edge("governor_retry", "mark_round_needed")
    g.add_conditional_edges("approval", r_approval, {
        "proceed": "record_decision",
        "skip": "mark_round_needed",
        "reject": "mark_execution_done",
    })
    g.add_conditional_edges("record_decision", r_action, {
        "CONVERGE": "apply_converge",
        "FIX_COMPILE_bug": "apply_compile_retry",
        "FIX_FUNCTIONAL_bug": "refactor_rtl",
        "FIX_PROTOCOL_bug": "refactor_rtl",
        "FIX_RESET_bug": "refactor_rtl",
        "FIX_CDC_bug": "refactor_rtl",
        "FIX_DEADCODE_bug": "refactor_rtl",
        "FIX_MODEL_bug": "apply_update_model",
        "GENERATE_DIRECTED_TEST": "apply_directed_test",
        "RELAX_CONSTRAINT": "apply_relax",
        "EXPAND_SEEDS": "apply_expand_seeds",
    })
    g.add_conditional_edges("apply_converge", r_after_converge, {
        "audit": "mark_execution_done"})
    g.add_conditional_edges("apply_compile_retry", r_after_compile_retry, {
        "next_round": "mark_round_needed", "abort": "mark_execution_done"})
    g.add_conditional_edges("refactor_rtl", r_after_guardian, {
        "next_round": "mark_round_needed", "abort": "mark_execution_done"})
    for name in ("apply_update_model", "apply_directed_test",
                 "apply_relax", "apply_expand_seeds"):
        g.add_edge(name, "mark_round_needed")
    g.add_edge("mark_round_needed", END)
    g.add_edge("mark_execution_done", END)
    return g.compile()


__all__ = [
    "build_design_subgraph", "build_verify_subgraph",
    "build_debug_subgraph", "build_coverage_subgraph",
]
