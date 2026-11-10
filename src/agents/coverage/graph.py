"""Coverage expert subgraph: coverage -> decide -> governor -> approval -> action."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.agents.coverage.loop import n_coverage_agent
from src.agents.runtime.markers import marker
from src.agents.runtime.nodes.agent.fix import (
    n_apply_compile_retry, n_apply_directed_test, n_apply_update_model,
    n_refactor_rtl,
)
from src.agents.runtime.nodes.agent.run import n_coverage
from src.agents.runtime.nodes.pure.apply import (
    n_apply_converge, n_apply_expand_seeds, n_apply_relax,
)
from src.agents.runtime.nodes.pure.approval import n_approval
from src.agents.runtime.nodes.pure.converge import (
    n_decide, n_governor, n_governor_retry, n_record_decision,
)
from src.agents.supervisor.routing import (
    r_action, r_after_compile_retry, r_after_converge, r_after_guardian,
    r_approval, r_governor,
)
from src.layers.l2_orchestration.state import PipelineState


def build_coverage_subgraph():
    g = StateGraph(PipelineState)
    for name, fn in (
        ("coverage", n_coverage),
        ("coverage_agent", n_coverage_agent),
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
    g.add_node("mark_round_needed", marker(
        debug_done=False, coverage_done=False, execution_done=False,
        coverage_attempts=1))
    g.add_node("mark_execution_done", marker(
        execution_done=True, coverage_done=True))

    g.add_edge(START, "coverage")
    g.add_edge("coverage", "coverage_agent")
    g.add_edge("coverage_agent", "decide")
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
