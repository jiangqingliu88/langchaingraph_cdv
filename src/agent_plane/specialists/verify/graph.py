"""Verify expert subgraph: verify -> verify_agent -> env_arch_check."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.orchestration_plane.markers import marker
from src.agent_plane.runtime.pipeline_nodes.build import n_verify
from src.orchestration_plane.nodes.pure.rounds import n_env_arch_check
from src.agent_plane.specialists.verify.loop import n_verify_agent
from src.orchestration_plane.l2.state import PipelineState


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
