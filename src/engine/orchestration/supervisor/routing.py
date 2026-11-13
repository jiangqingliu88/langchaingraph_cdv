"""条件边路由 —— 「下一步走哪」只在这里回答

每个 `r_*` 只看状态、返回一个字符串；图里的 `add_conditional_edges` 用它那张表。
**拓扑的权威在 `graph.py` 的 `add_conditional_edges`**，这里只负责判。
"""
from __future__ import annotations

import structlog

# `r_after_round_bump` 与 `n_round_bump` 判的是**同一件事**（还有没有轮次预算）——
# 判据只能有一份，所以从节点那边 import，而不是在这里再写一遍 `state.round_num < max_rounds`。
from src.engine.orchestration.nodes.pure.rounds import _have_rounds_left
from src.layers.l2_orchestration.state import PipelineState
from src.layers.l3_decision.decision_engine import Action

logger = structlog.get_logger()


def r_after_design(state: PipelineState) -> str:
    """design/design_agent 之后的分流：没 RTL 就直接去 audit。"""
    return "abort" if (state.interrupted or state.rtl_missing) else "ok"


def r_after_round_bump(state: PipelineState) -> str:
    """轮次预算的唯一把关点。

    `round_bump` 是**所有回边的汇合处**：governor_retry / approval-skip /
    apply_compile_retry / guardian / update_model / directed_test / relax /
    expand_seeds 全都回到这里，再从它进 `ops`。所以预算只在这里查一次就够 ——
    不必在八条回边上各写一遍（写八遍就是八份真相，漏一处就是又一轮失控）。

    预算用尽走 `audit`（与 governor 的 abort 同一条出口）：**如实签核**，
    结果里的 `converged` 由 `effective_coverage >= target` 推出来，所以"轮次用尽
    但没达标"会如实记成未收敛，而不是假装通过。
    """
    if _have_rounds_left(state):
        return "next_round"
    logger.info(f"轮次预算用尽（已跑 {state.round_num - 1} 轮 / 上限 {state.max_rounds}），"
                f"退出闭环进入签核：覆盖率 {state.final_coverage}% / 目标 {state.target}%")
    return "give_up"


def r_governor(state: PipelineState) -> str:
    """熔断后：override/proceed 继续；retry 回下一轮（continue）；其余终止（break）。"""
    outcome = state.governance_outcome
    if outcome in ("proceed", "override"):
        return "proceed"
    if outcome == "retry":
        # 人工放行 → 复位熔断，等价于原来的 continue
        return "retry"
    return "abort"


def r_approval(state: PipelineState) -> str:
    o = state.approval_outcome
    if o == "reject":
        return "reject"
    if o == "skip":
        return "skip"
    return "proceed"


def r_action(state: PipelineState) -> str:
    """动作分流。未映射的动作显式报错——原来 if/elif 没有 else，
    未映射的 action_type 会静默重开一轮。

    **先归一**（`canonical_action`）：老名字（`REFACTOR_RTL` / `COMPILE_RETRY` /
    `UPDATE_MODEL`）映射到 `FIX_*_bug` 的分类名 —— RL 策略文件和历史轨迹里存的是
    老名字，直接比会判成"未映射"。
    """
    from src.layers.l3_decision.decision_engine import canonical_action

    at = canonical_action((state.action() or Action("")).action_type)
    allowed = {"CONVERGE", "FIX_COMPILE_bug", "FIX_MODEL_bug", "FIX_FUNCTIONAL_bug",
               "FIX_PROTOCOL_bug", "FIX_RESET_bug", "FIX_CDC_bug", "FIX_DEADCODE_bug",
               "GENERATE_DIRECTED_TEST", "RELAX_CONSTRAINT", "EXPAND_SEEDS"}
    if at not in allowed:
        raise ValueError(
            f"决策层返回了未映射的动作 {at!r}；decision_engine 的动作全集见 "
            "ACTION_HANDLERS，新增动作必须同时补 execution 的分支"
        )
    return at


def r_after_compile_retry(state: PipelineState) -> str:
    if state.interrupted:
        return "abort"
    return _round_or_abort(state)


def r_after_guardian(state: PipelineState) -> str:
    if state.interrupted:
        return "abort"
    return _round_or_abort(state)


def _round_or_abort(state: PipelineState) -> str:
    """还有下一轮就回 round_bump，否则去签核。

    **这一条最容易漏**：原来 `for range(max_rounds)` 隐式做了边界检查，
    图里必须显式写出来，否则会多跑一轮。
    """
    if state.round_num >= state.max_rounds:
        return "abort"
    return "next_round"


def r_coverage(state: PipelineState) -> str:
    """ops 之后的分流：EDA 缺失 / 人工节点 / 编译失败 / 功能回归失败 / 正常收覆盖率。"""
    if state.eda_blocked:
        return "eda_missing"
    if state.awaiting_approval:
        # 回归停在 loopback 等人放行 —— 和人有关的事，机器别空转。
        # 与 `eda_missing` 同一个出口：直接去 audit 收尾，不跑 coverage/decide。
        return "awaiting_approval"
    if state.regression_failed_count and not state.compile_error:
        return "functional_fail"
    if state.compile_error:
        return "compile_fail"
    return "run_coverage"


def r_after_converge(state: PipelineState) -> str:
    """收敛即离开循环去签核（原来 CONVERGE 分支末尾 break）。"""
    return "audit"


