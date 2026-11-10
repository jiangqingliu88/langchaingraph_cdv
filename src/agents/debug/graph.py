"""Debug expert subgraph: round_bump -> ops -> debug loop (cycle)."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.agents.debug.loop import n_debug_agent
from src.agents.runtime.markers import marker
from src.agents.runtime.nodes.agent.run import n_debug_functional, n_ops
from src.agents.runtime.nodes.pure.rounds import n_round_bump
from src.agents.supervisor.routing import r_after_round_bump, r_coverage
from src.layers.l2_orchestration.state import PipelineState


def build_debug_subgraph():
    g = StateGraph(PipelineState)
    g.add_node("round_bump", n_round_bump)
    g.add_node("ops", n_ops)
    g.add_node("agent_loop", n_debug_agent)
    g.add_node("debug_functional", n_debug_functional)
    g.add_node("mark_debug_attempt", marker(debug_attempts=1))
    g.add_node("mark_debug_done", marker(debug_done=True))
    g.add_node("mark_execution_done", marker(execution_done=True))

    g.add_edge(START, "round_bump")
    g.add_conditional_edges("round_bump", r_after_round_bump, {
        "next_round": "ops",
        "give_up": "mark_execution_done",
    })
    g.add_conditional_edges("ops", r_coverage, {
        "eda_missing": "mark_execution_done",
        "awaiting_approval": "mark_execution_done",
        "compile_fail": "agent_loop",
        "functional_fail": "agent_loop",
        "run_coverage": "mark_debug_done",
    })
    g.add_edge("agent_loop", "debug_functional")
    g.add_edge("debug_functional", "mark_debug_attempt")
    g.add_edge("mark_debug_attempt", "round_bump")
    g.add_edge("mark_debug_done", END)
    g.add_edge("mark_execution_done", END)
    return g.compile()
