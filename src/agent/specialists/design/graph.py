"""Design expert subgraph: front -> design -> design_agent (opt-in) -> model."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.agent.specialists.design.loop import n_design_agent
from src.engine.orchestration.markers import marker
from src.agent.runtime.pipeline_nodes.build import n_design, n_front, n_model
from src.engine.orchestration.supervisor.routing import r_after_design
from src.layers.l2_orchestration.state import PipelineState


def build_design_subgraph():
    g = StateGraph(PipelineState)
    g.add_node("front", n_front)
    g.add_node("design", n_design)
    g.add_node("design_agent", n_design_agent)
    g.add_node("model", n_model)
    g.add_node("mark_design_done", marker(design_done=True))
    g.add_edge(START, "front")
    g.add_edge("front", "design")
    g.add_edge("design", "design_agent")
    g.add_conditional_edges("design_agent", r_after_design, {
        "ok": "model",
        "abort": "mark_design_done",
    })
    g.add_edge("model", "mark_design_done")
    g.add_edge("mark_design_done", END)
    return g.compile()
