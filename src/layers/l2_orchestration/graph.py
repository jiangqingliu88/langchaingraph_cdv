"""闭环流水线的 StateGraph —— **只负责「节点怎么连起来」**。

这个文件只做三件事
    1. 从 `nodes/` 取 24 个节点函数，组装成 `NODE_FUNCS`（"有哪些节点"的唯一清单）
    2. 用 `add_node` / `add_conditional_edges` 把边连出来
    3. 收口 `recursion_limit`

    节点实现搬去了 `nodes/`（pure 12 + agent 12），判分逻辑搬去了 `routers.py`，
    运行期对象搬去了 `runtime.py`。**拆之前这里是 1741 行、33 个函数定义；
    建图本身只有 90 行左右** —— 那 90 行才是这个文件该有的样子。

为什么留这么多 re-export
    原来 `n_approval` / `r_action` / `Runtime` 这些名字都住在 `graph.py` 里，
    `execution.py` 与一批测试直接从这儿 import。**拆文件改的是"东西放哪"，
    不是"东西叫什么"** —— 让调用方跟着改一遍纯属自找麻烦（而且改漏一处就
    是 ImportError）。所以这里留兼容出口，新代码请直接从 `nodes/` / `routers.py`
    / `runtime.py` 取。

拓扑的权威在这里
    路由函数（`routers.py`）只回答"下一步是哪个字符串"；**字符串到节点的映射
    在下面的 `add_conditional_edges` 表里**。两处要一起看才完整 —— 这也是
    `stages.py` 的模块头说"加一个节点是三处"里没有的那一处（另两处是
    `graph.py` 的 `NODE_FUNCS` 和 `stages.py` 的 `STAGES`）。
"""
from __future__ import annotations

import functools
import os
from typing import Any, Dict, List, Optional

import structlog
from langgraph.graph import END, START, StateGraph

from src.layers.l2_orchestration.nodes.agent.build import (n_design, n_front,
                                                           n_model, n_verify)
from src.layers.l2_orchestration.nodes.agent.fix import (
    n_apply_compile_retry, n_apply_directed_test, n_apply_update_model,
    n_refactor_rtl)
from src.layers.l2_orchestration.nodes.agent.run import (n_coverage,
                                                          n_debug_functional, n_ops)
from src.layers.l2_orchestration.nodes.agent.signoff import n_audit
from src.layers.l2_orchestration.nodes.pure.apply import (n_apply_converge,
                                                          n_apply_expand_seeds,
                                                          n_apply_relax)
from src.layers.l2_orchestration.nodes.pure.approval import (
    _LEGACY_HIGH_RISK_ACTIONS, _approval_artifacts, _interrupt_approval,
    _matching_manual_node, n_approval)
from src.layers.l2_orchestration.nodes.pure.converge import (
    n_decide, n_governor, n_governor_retry, n_record_decision)
from src.layers.l2_orchestration.nodes.pure.lifecycle import (n_finalize,
                                                              n_init)
from src.layers.l2_orchestration.nodes.pure.rounds import (
    n_env_arch_check, n_round_bump)
from src.layers.l2_orchestration.routers import (
    r_action, r_after_compile_retry, r_after_converge, r_after_design,
    r_after_guardian, r_after_round_bump, r_approval, r_coverage, r_governor)
from src.layers.l2_orchestration.runtime import (Runtime, hydrate_runtime,
                                                 recursion_limit)
from src.layers.l2_orchestration.state import (
    CRITICAL_STATE_FIELDS, PipelineState, unexpected_state_writers)

logger = structlog.get_logger()

# ── 兼容出口：调用方（execution.py 与若干测试）原来从 graph 取这些名字 ──
_ = (_LEGACY_HIGH_RISK_ACTIONS, _approval_artifacts, _interrupt_approval,
     _matching_manual_node, n_approval, r_action, r_coverage,
     Runtime, hydrate_runtime, recursion_limit)

__all__ = ["NODE_FUNCS", "NODE_NAMES", "build_closed_loop_graph",
           "build_legacy_closed_loop_graph", "build_supervisor_graph",
           "Runtime", "hydrate_runtime", "recursion_limit"]


NODE_FUNCS = (
    ("init", n_init), ("front", n_front), ("design", n_design), ("model", n_model), ("verify", n_verify),
    ("env_arch_check", n_env_arch_check), ("round_bump", n_round_bump),
    ("ops", n_ops), ("coverage", n_coverage), ("debug_functional", n_debug_functional),
    ("decide", n_decide), ("governor", n_governor),
    ("governor_retry", n_governor_retry), ("approval", n_approval),
    ("record_decision", n_record_decision),
    ("apply_converge", n_apply_converge),
    ("apply_compile_retry", n_apply_compile_retry),
    ("refactor_rtl", n_refactor_rtl), ("apply_update_model", n_apply_update_model),
    ("apply_directed_test", n_apply_directed_test), ("apply_relax", n_apply_relax),
    ("apply_expand_seeds", n_apply_expand_seeds),
    ("audit", n_audit), ("finalize", n_finalize),
)

NODE_NAMES = tuple(name for name, _ in NODE_FUNCS)

#: 已经告警过的 (节点, 字段) —— 同一处只提醒一次，避免每轮刷屏。
_STATE_WARNED: set = set()


def _guarded_node(name: str, fn):
    """包一层 State 契约检查：越权写**关键字段** → 硬失败，其余 → warning。

    `tests` / `coverage` / `audit` / `result` 被非属主覆盖 = 身份或结论被静默
    篡改，不能只留一条日志；其余字段仍只告警（LangGraph 的 reducer 是合并权威，
    小范围观察哨没必要拦死）。`SIGNOFFAI_STATE_CONTRACT=warn` 可整体退回告警。
    包装函数保持 `(state, config)` 签名。
    """
    if getattr(fn, "__state_guard__", False):
        return fn

    @functools.wraps(fn)
    async def _wrapped(state, config):
        update = await fn(state, config)
        if isinstance(update, dict):
            bad = unexpected_state_writers(name, update)
            strict = os.environ.get(
                "SIGNOFFAI_STATE_CONTRACT", "strict").strip().lower() != "warn"
            critical = [f for f in bad if f in CRITICAL_STATE_FIELDS]
            if strict and critical:
                raise RuntimeError(
                    f"State 契约违规（硬失败）: 节点 {name!r} 写了不属于它的关键"
                    f"字段 {critical}（写入者见 state.STATE_CONTRACTS；"
                    f"如确属无害，用 SIGNOFFAI_STATE_CONTRACT=warn 退回告警）")
            for field in bad:
                key = (name, field)
                if key in _STATE_WARNED:
                    continue
                _STATE_WARNED.add(key)
                logger.warning(
                    f"State 契约告警: 节点 {name!r} 写了不属于它的字段 "
                    f"{field!r}（写入者见 state.STATE_CONTRACTS）")
        return update

    _wrapped.__state_guard__ = True
    return _wrapped


def build_legacy_closed_loop_graph(checkpointer=None, store=None):
    """构建旧的 24 节点单图（测试基线 / Supervisor 回滚路径）。

    拓扑（与 run_closed_loop 的语句顺序一一对应）：
      init → design → model → verify → env_arch_check → round_bump
      round_bump → ops → {eda_missing→audit | compile_fail→decide
                          | functional_fail→debug→decide | run_coverage→coverage→decide}
      decide → governor → {proceed|override→approval → record → 动作分支}
                         {retry→round_bump} {abort→audit}
      各动作分支 → round_bump（或 converge/abort → audit）
      audit → finalize → END
    """
    g = StateGraph(PipelineState)

    for name, fn in NODE_FUNCS:
        g.add_node(name, _guarded_node(name, fn))

    g.add_edge(START, "init")
    g.add_edge("init", "front")
    g.add_edge("front", "design")   # front 不通过时由 interrupted 送 audit
    # design 之后加一道**RTL 门禁**：没产出 RTL 就走 audit，不带病往下跑
    g.add_conditional_edges("design", r_after_design, {
        "ok": "model",      # bypass 时 n_model 自行跳过
        "abort": "audit",
    })
    g.add_edge("model", "verify")
    g.add_edge("verify", "env_arch_check")
    g.add_edge("env_arch_check", "round_bump")
    # round_bump 是所有回边的汇合点 —— 轮次预算在这里收口（见 r_after_round_bump）
    g.add_conditional_edges("round_bump", r_after_round_bump, {
        "next_round": "ops",
        "give_up": "audit",
    })

    g.add_conditional_edges("ops", r_coverage, {
        "eda_missing": "audit",
        "awaiting_approval": "audit",
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
        "abort": "audit",
    })
    g.add_edge("governor_retry", "round_bump")

    g.add_conditional_edges("approval", r_approval, {
        "proceed": "record_decision",
        "skip": "round_bump",
        "reject": "audit",
    })

    g.add_conditional_edges("record_decision", r_action, {
        "CONVERGE": "apply_converge",
        "FIX_COMPILE_bug": "apply_compile_retry",
        # 改 RTL 的三类走同一个节点（都要过回归守卫 + 重跑比对）
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

    g.add_conditional_edges("apply_converge", r_after_converge, {"audit": "audit"})
    g.add_conditional_edges("apply_compile_retry", r_after_compile_retry, {
        "next_round": "round_bump", "abort": "audit"})
    g.add_conditional_edges("refactor_rtl", r_after_guardian, {
        "next_round": "round_bump", "abort": "audit"})
    g.add_edge("apply_update_model", "round_bump")
    g.add_edge("apply_directed_test", "round_bump")
    g.add_edge("apply_relax", "round_bump")
    g.add_edge("apply_expand_seeds", "round_bump")

    g.add_edge("audit", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer, store=store)


def build_closed_loop_graph(checkpointer=None, store=None):
    """当前默认入口：Supervisor 主图 + 专家子图。

    回滚：`SIGNOFFAI_SUPERVISOR=off`（或直接调用
    `build_legacy_closed_loop_graph()`）回到 24 节点单图。
    默认值刻意是 **on**：新架构才是当前实现，旧图只作兼容/对照。
    """
    mode = os.environ.get("SIGNOFFAI_SUPERVISOR", "on").strip().lower()
    if mode in ("off", "0", "false", "legacy"):
        return build_legacy_closed_loop_graph(
            checkpointer=checkpointer, store=store)
    from .supervisor.graph import build_supervisor_graph

    return build_supervisor_graph(checkpointer=checkpointer, store=store)
