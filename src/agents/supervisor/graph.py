"""Supervisor 主图 —— 只回答“下一步派哪个专家”，不执行 EDA、不做判定。

拓扑（主图 9 个节点）：

    START → init → supervisor
      supervisor ──design──► design_expert ──► supervisor
      supervisor ──verify──► verify_expert ──► supervisor
      supervisor ──debug──► debug_expert ──► supervisor
      supervisor ──coverage──► coverage_expert ──► supervisor
      supervisor ──human_review──► human_review ──► supervisor
      supervisor ──audit──► audit_gate ──► finalize → END

`debug_expert` / `coverage_expert` 内部各自有循环；主图只保留 supervisor 这一条
受控回边。`supervisor_visits` 是主图自己的防失控计数，轮次预算仍由
`round_bump`（debug_expert 内）收口。
"""
from __future__ import annotations

from typing import Any, Dict

import structlog
from langgraph.graph import END, START, StateGraph

from src.agents.coverage.graph import build_coverage_subgraph
from src.agents.debug.graph import build_debug_subgraph
from src.agents.design.graph import build_design_subgraph
from src.agents.gates.audit import n_hard_audit_gate
from src.agents.gates.human import n_human_review
from src.agents.registry import card
from src.agents.runtime.nodes.pure.lifecycle import n_finalize, n_init
from src.agents.supervisor.state import SupervisorView
from src.agents.verify.graph import build_verify_subgraph
from src.layers.l2_orchestration.state import PipelineState

logger = structlog.get_logger()

#: 主图节点名（权威清单；stages/工作台从 here 读）。
NODE_NAMES = (
    "init", "supervisor", "design_expert", "verify_expert", "debug_expert",
    "coverage_expert", "human_review", "audit_gate", "finalize",
)
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
    elif (view.debug_attempts >= card("debug").requires_human_after
          and not view.human_reviewed):
        choice = "human_review"
        reason = f"Debug 已连续返工 {view.debug_attempts} 次，暂停让人确认"
    elif view.coverage_attempts >= card("coverage").max_attempts:
        choice = "audit"
        reason = (f"coverage 循环 {view.coverage_attempts} 次达到 AgentCard 上限")
    elif not view.coverage_done:
        choice = "coverage"
        reason = "回归已通过，进入 coverage_expert"
    else:
        choice = "audit"
        reason = "所有专家已完成，进入硬审计"
    logger.info(f"Supervisor → {choice}（{reason}）")
    update = {
        "next_agent": choice,
        "supervisor_visits": 1,
        "supervisor_trace": [{"visit": visits, "next": choice, "reason": reason}],
    }
    if choice == "audit" and "coverage" in reason and "上限" in reason:
        update["terminal_reason"] = "coverage_budget_exhausted"
    return update


def r_supervisor(state: PipelineState) -> str:
    """主图条件边：只认五个合法值。"""
    choice = str(state.next_agent or "")
    if choice in ("design", "verify", "debug", "coverage",
                  "human_review", "audit"):
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
    g.add_node("human_review", n_human_review)
    g.add_node("audit_gate", n_hard_audit_gate)
    g.add_node("finalize", n_finalize)

    g.add_edge(START, "init")
    g.add_edge("init", "supervisor")
    g.add_conditional_edges("supervisor", r_supervisor, {
        "design": "design_expert",
        "verify": "verify_expert",
        "debug": "debug_expert",
        "coverage": "coverage_expert",
        "human_review": "human_review",
        "audit": "audit_gate",
    })
    for expert in ("design_expert", "verify_expert", "debug_expert",
                   "coverage_expert", "human_review"):
        g.add_edge(expert, "supervisor")
    g.add_edge("audit_gate", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer, store=store)


#: 节点名 → 构建器/函数（工作台只读名字；测试检查清单一致）。
NODE_FUNCS = (
    ("init", n_init), ("supervisor", n_supervisor),
    ("design_expert", build_design_subgraph),
    ("verify_expert", build_verify_subgraph),
    ("debug_expert", build_debug_subgraph),
    ("coverage_expert", build_coverage_subgraph),
    ("human_review", n_human_review),
    ("audit_gate", n_hard_audit_gate),
    ("finalize", n_finalize),
)

__all__ = ["build_supervisor_graph", "build_closed_loop_graph", "NODE_NAMES",
           "NODE_FUNCS", "n_supervisor", "r_supervisor",
           "MAX_SUPERVISOR_VISITS"]


def build_closed_loop_graph(checkpointer=None, store=None):
    """Canonical entry point for the agentic graph."""
    return build_supervisor_graph(checkpointer=checkpointer, store=store)
