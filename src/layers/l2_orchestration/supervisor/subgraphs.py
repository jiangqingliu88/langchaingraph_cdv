"""专家子图 —— 主图只挂这些编译后的图，不直接铺 24 个节点。

两个专家：

    design_expert      front → design → model → verify → env_arch_check
    execution_expert   round_bump → ops → (coverage | debug) → decide
                       → governor → approval → record_decision → 动作 → round_bump

`design_expert` 是线性子图（设计执行器内部已有“生成→编译→重试”循环）；
`execution_expert` 保留原来的轮次循环，是有**环形边**的子图。
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
    """设计专家：前置分析 → 设计/模型/验证 → env 架构检查。"""
    g = StateGraph(PipelineState)
    g.add_node("front", n_front)
    g.add_node("design", n_design)
    g.add_node("model", n_model)
    g.add_node("verify", n_verify)
    g.add_node("env_arch_check", n_env_arch_check)
    g.add_node("mark_design_done", _marker(design_done=True))

    g.add_edge(START, "front")
    g.add_edge("front", "design")
    g.add_conditional_edges("design", r_after_design, {
        "ok": "model",
        "abort": "mark_design_done",
    })
    g.add_edge("model", "verify")
    g.add_edge("verify", "env_arch_check")
    g.add_edge("env_arch_check", "mark_design_done")
    g.add_edge("mark_design_done", END)
    return g.compile()


def build_execution_subgraph():
    """执行专家：保留原闭环的轮次/调试/覆盖率循环，结束交回 Supervisor。"""
    g = StateGraph(PipelineState)
    for name, fn in (
        ("round_bump", n_round_bump),
        ("ops", n_ops),
        ("coverage", n_coverage),
        ("debug_functional", n_debug_functional),
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
    g.add_node("mark_execution_done", _marker(execution_done=True))

    g.add_edge(START, "round_bump")
    g.add_conditional_edges("round_bump", r_after_round_bump, {
        "next_round": "ops",
        "give_up": "mark_execution_done",
    })
    g.add_conditional_edges("ops", r_coverage, {
        "eda_missing": "mark_execution_done",
        "awaiting_approval": "mark_execution_done",
        "compile_fail": "decide",
        "functional_fail": "debug_functional",
        "run_coverage": "coverage",
    })
    g.add_edge("debug_functional", "decide")
    g.add_edge("coverage", "decide")
    g.add_edge("decide", "governor")
    g.add_conditional_edges("governor", r_governor, {
        "proceed": "approval",
        "retry": "governor_retry",
        "abort": "mark_execution_done",
    })
    g.add_edge("governor_retry", "round_bump")
    g.add_conditional_edges("approval", r_approval, {
        "proceed": "record_decision",
        "skip": "round_bump",
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
        "next_round": "round_bump", "abort": "mark_execution_done"})
    g.add_conditional_edges("refactor_rtl", r_after_guardian, {
        "next_round": "round_bump", "abort": "mark_execution_done"})
    g.add_edge("apply_update_model", "round_bump")
    g.add_edge("apply_directed_test", "round_bump")
    g.add_edge("apply_relax", "round_bump")
    g.add_edge("apply_expand_seeds", "round_bump")
    g.add_edge("mark_execution_done", END)
    return g.compile()


__all__ = ["build_design_subgraph", "build_execution_subgraph"]
