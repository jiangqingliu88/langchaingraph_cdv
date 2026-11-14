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

from typing import Any, Dict, List, get_origin

import structlog
from langgraph.graph import END, START, StateGraph

from src.agent_plane.specialists.coverage.graph import build_coverage_subgraph
from src.agent_plane.specialists.debug.graph import build_debug_subgraph
from src.agent_plane.specialists.design.graph import build_design_subgraph
from src.orchestration_plane.gates.audit import n_hard_audit_gate
from src.orchestration_plane.gates.human import n_human_review
from src.orchestration_plane.registry import card
from src.orchestration_plane.nodes.pure.lifecycle import n_finalize, n_init
from src.orchestration_plane.supervisor.state import SupervisorView
from src.agent_plane.specialists.verify.graph import build_verify_subgraph
from src.orchestration_plane.l2.state import PipelineState, _add

logger = structlog.get_logger()


def _additive_fields() -> Dict[str, Any]:
    """状态里所有 `Annotated[..., _add]` 字段 → 归零值。

    LangGraph 把子图当节点时，子图**输出会带上它继承来的整份状态**，父图再
    按 reducer 合并 —— 于是 `_add` 字段的继承值被**再加一遍**：

        supervisor 读 visits=0 → +1=1 → 子图带 1 进去、原样带 1 出来
        → 父图 1+1=2 → 下次 supervisor 读到 2 → visit=3 → 2(3+1)×2=6 …

    实测 supervisor 访问数按 1/3/7/15/31 指数增长，1 轮就跑满
    MAX_SUPERVISOR_VISITS 强转 audit；`phases`/`debug_attempts`/`round_num`
    同样被放大。修复见 `_delta_only`：子图只回传**本段的增量**。
    """
    out: Dict[str, Any] = {}
    for name, field in PipelineState.model_fields.items():
        if not any(m is _add for m in field.metadata):
            continue
        out[name] = [] if get_origin(field.annotation) in (list, List) else 0
    return out


_ADDITIVE = _additive_fields()


def _delta_only(before, after):
    """子图输出 → 只保留本段增量（父图的 reducer 负责叠加）。"""
    b = before if isinstance(before, dict) else before.model_dump()
    a = after if isinstance(after, dict) else after.model_dump()
    out = dict(a)
    for name, ident in _ADDITIVE.items():
        if name not in out:
            continue
        old = b.get(name, ident)
        new = out[name]
        if isinstance(ident, list):
            # `_add` 对 list 是连接：子图输出 = 继承值 + 本段追加。
            if (isinstance(old, list) and isinstance(new, list)
                    and new[:len(old)] == old):
                out[name] = new[len(old):]
            else:
                logger.warning(f"子图输出不是继承值的前缀拼接，无法做增量还原: {name}")
        elif isinstance(old, int) and isinstance(new, int):
            out[name] = new - old
    return out


def _expert(subgraph):
    """把专家子图包成主图节点：只回传增量，避免 `_add` 字段被子图边界重复累加。"""
    async def node(state, config):
        out = await subgraph.ainvoke(state, config)
        return _delta_only(state, out)

    node.__name__ = getattr(subgraph, "name", "expert")
    return node

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
    # 专家子图必须经 `_expert` 包一层：子图输出会带上继承状态，`_add` 字段
    # 在边界处会被重复累加（supervisor 访问数按 1/3/7/15/31 指数增长）。
    g.add_node("design_expert", _expert(build_design_subgraph()))
    g.add_node("verify_expert", _expert(build_verify_subgraph()))
    g.add_node("debug_expert", _expert(build_debug_subgraph()))
    g.add_node("coverage_expert", _expert(build_coverage_subgraph()))
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
