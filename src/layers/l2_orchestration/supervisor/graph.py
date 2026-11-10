"""Supervisor 主图 —— 只回答“下一步派哪个专家”，不执行 EDA、不做判定。

拓扑：

    START → init → supervisor
      supervisor ──design──► design_expert ──► supervisor
      supervisor ──execution──► execution_expert ──► supervisor
      supervisor ──audit──► audit_gate ──► finalize → END

子图内部各自有循环/阶段；主图只保留一条受控回边。`supervisor_visits` 是
主图自己的防失控计数，轮次预算仍由执行子图里的 `round_bump` 收口。
"""
from __future__ import annotations

from typing import Any, Dict

import structlog
from langgraph.graph import END, START, StateGraph

from src.layers.l2_orchestration.nodes.pure.lifecycle import n_finalize, n_init
from src.layers.l2_orchestration.state import PipelineState

from .audit import n_hard_audit_gate
from .state import SupervisorView
from .subgraphs import build_design_subgraph, build_execution_subgraph

logger = structlog.get_logger()

#: 主图最多在 supervisor 上转几圈（不是轮次预算；防流程图自身死循环）。
MAX_SUPERVISOR_VISITS = 12


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
    elif not view.design_done:
        choice = "design"
        reason = "design_expert 尚未完成"
    elif not view.execution_done:
        choice = "execution"
        reason = "design 已完成，进入执行专家"
    else:
        choice = "audit"
        reason = "执行专家已返回，进入硬审计"
    logger.info(f"Supervisor → {choice}（{reason}）")
    return {
        "next_agent": choice,
        "supervisor_visits": 1,
        "supervisor_trace": [{"visit": visits, "next": choice, "reason": reason}],
    }


def r_supervisor(state: PipelineState) -> str:
    """主图条件边：只认 `next_agent` 的四个合法值。"""
    choice = str(state.next_agent or "")
    if choice in ("design", "execution", "audit"):
        return choice
    return "audit"


def build_supervisor_graph(checkpointer=None, store=None):
    """编译 Supervisor 主图（设计/执行专家是独立子图）。"""
    g = StateGraph(PipelineState)
    g.add_node("init", n_init)
    g.add_node("supervisor", n_supervisor)
    g.add_node("design_expert", build_design_subgraph())
    g.add_node("execution_expert", build_execution_subgraph())
    g.add_node("audit_gate", n_hard_audit_gate)
    g.add_node("finalize", n_finalize)

    g.add_edge(START, "init")
    g.add_edge("init", "supervisor")
    g.add_conditional_edges("supervisor", r_supervisor, {
        "design": "design_expert",
        "execution": "execution_expert",
        "audit": "audit_gate",
    })
    g.add_edge("design_expert", "supervisor")
    g.add_edge("execution_expert", "supervisor")
    g.add_edge("audit_gate", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer, store=store)


__all__ = ["build_supervisor_graph", "n_supervisor", "r_supervisor",
           "MAX_SUPERVISOR_VISITS"]
