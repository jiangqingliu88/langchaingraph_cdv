"""Verify expert subgraph: verify -> verify_agent -> env_arch_check."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.agents.runtime.markers import marker
from src.agents.runtime.nodes.agent.build import n_verify
from src.agents.runtime.nodes.pure.rounds import n_env_arch_check
from src.agents.verify.loop import n_verify_agent
from src.layers.l2_orchestration.state import PipelineState


def build_verify_subgraph():
    g = StateGraph(PipelineState)
    g.add_node("verify", n_verify)
    g.add_node("verify_agent", n_verify_agent)
    g.add_node("env_arch_check", n_env_arch_check)
    g.add_node("mark_verify_done", marker(verify_done=True))
    g.add_edge(START, "verify")
    g.add_edge("verify", "verify_agent")
    g.add_edge("verify_agent", "env_arch_check")
    g.add_edge("env_arch_check", "mark_verify_done")
    g.add_edge("mark_verify_done", END)
    return g.compile()
