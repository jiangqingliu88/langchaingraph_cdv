"""Supervisor 主图 —— 只回答“下一步派哪个专家”，不执行 EDA、不做判定。

拓扑（主图 8 个节点）：

    START → init → supervisor
      supervisor ──design──► design_expert ──► supervisor
      supervisor ──verify──► verify_expert ──► supervisor
      supervisor ──debug──► debug_expert ──► supervisor
      supervisor ──coverage──► coverage_expert ──► supervisor
      supervisor ──audit──► audit_gate ──► finalize → END

`debug_expert` / `coverage_expert` 内部各自有循环；主图只保留 supervisor 这一条
受控回边。`supervisor_visits` 是主图自己的防失控计数，轮次预算仍由
`round_bump`（debug_expert 内）收口。
"""
from __future__ import annotations

from typing import Any, Dict

import structlog
from langgraph.graph import END, START, StateGraph

from src.layers.l2_orchestration.nodes.pure.lifecycle import n_finalize, n_init
from src.layers.l2_orchestration.state import PipelineState

from .audit import n_hard_audit_gate
from .state import SupervisorView
from .subgraphs import (
    build_coverage_subgraph, build_debug_subgraph, build_design_subgraph,
    build_verify_subgraph,
)

logger = structlog.get_logger()

#: 主图最多在 supervisor 上转几圈（不是轮次预算；防流程图自身死循环）。
MAX_SUPERVISOR_VISITS = 24


async def n_supervisor(state: PipelineState, config) -> Dict[str, Any]:
    """只读状态、写路由字段；不调 LLM、不跑工具、不改专家产物。"""
    view = SupervisorView.from_state(state)
    visits = view.visits + 1
    if visits > MAX_SUPERVISOR_VISITS:
        choice = "audit"
        reason = f"supervisor 访问次数 {visits} 超过上限 {MAX_SUPERVISOR_VISITS}"
    elif view.interrupted or view.eda_blocked or view.awaiting_approval:
        choice = "audit"
        reason = f"终止信号 terminal_reason={view.terminal_reason}"
    elif view.execution_done:
        choice = "audit"
        reason = "execution_done=true，进入硬审计"
    elif not view.design_done:
        choice = "design"
        reason = "design_expert 尚未完成"
    elif not view.verify_done:
        choice = "verify"
        reason = "design 已完成，进入 verify_expert"
    elif not view.debug_done:
        choice = "debug"
        reason = "verify 已完成，进入 debug_expert"
    elif not view.coverage_done:
        choice = "coverage"
        reason = "回归已通过，进入 coverage_expert"
    else:
        choice = "audit"
        reason = "所有专家已完成，进入硬审计"
    logger.info(f"Supervisor → {choice}（{reason}）")
    return {
        "next_agent": choice,
        "supervisor_visits": 1,
        "supervisor_trace": [{"visit": visits, "next": choice, "reason": reason}],
    }


def r_supervisor(state: PipelineState) -> str:
    """主图条件边：只认五个合法值。"""
    choice = str(state.next_agent or "")
    if choice in ("design", "verify", "debug", "coverage", "audit"):
        return choice
    return "audit"


def build_supervisor_graph(checkpointer=None, store=None):
    """编译 Supervisor 主图（4 个专家子图 + 纯审计门）。"""
    g = StateGraph(PipelineState)
    g.add_node("init", n_init)
    g.add_node("supervisor", n_supervisor)
    g.add_node("design_expert", build_design_subgraph())
    g.add_node("verify_expert", build_verify_subgraph())
    g.add_node("debug_expert", build_debug_subgraph())
    g.add_node("coverage_expert", build_coverage_subgraph())
    g.add_node("audit_gate", n_hard_audit_gate)
    g.add_node("finalize", n_finalize)

    g.add_edge(START, "init")
    g.add_edge("init", "supervisor")
    g.add_conditional_edges("supervisor", r_supervisor, {
        "design": "design_expert",
        "verify": "verify_expert",
        "debug": "debug_expert",
        "coverage": "coverage_expert",
        "audit": "audit_gate",
    })
    for expert in ("design_expert", "verify_expert", "debug_expert",
                   "coverage_expert"):
        g.add_edge(expert, "supervisor")
    g.add_edge("audit_gate", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer, store=store)


__all__ = ["build_supervisor_graph", "n_supervisor", "r_supervisor",
           "MAX_SUPERVISOR_VISITS"]
