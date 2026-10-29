"""纯函数节点 · 决策与治理

调决策引擎 / 治理门控 / 决策记账 —— 全是确定性逻辑，不碰 executor。
"""
from __future__ import annotations

from typing import Any, Dict

from pathlib import Path
import json

import structlog

from src.layers.l2_orchestration.runtime import (
    _rt,
)
from src.layers.l2_orchestration.state import PipelineState
from src.layers.l3_decision.decision_engine import Action, Observation

logger = structlog.get_logger()


async def n_decide(state: PipelineState, config) -> Dict[str, Any]:
    """构造 Observation → 语义增强 → 决策（规则引擎 / DecisionReactor）。"""
    rt = _rt(config)
    failed = state.regression_failed_count

    # 功能回归失败 → failed_tests 非空 → 决策层走 REFACTOR_RTL
    _failed_tests = ([f"functional_regress_r{state.round_num}"]
                     if (failed and not state.compile_error) else [])
    obs = Observation(
        iteration_id=state.round_num - 1,
        coverage={"functional": state.effective_coverage},
        gaps=state.gaps,
        failed_tests=_failed_tests,
        coverage_history=state.coverage_history + [state.effective_coverage],
        compile_error=state.compile_error,
        sim_reward=state.sim_reward,
    )

    # 语义化：用 Verification Knowledge Graph 补 gap_paths（精准归因）
    try:
        from src.layers.l3_decision.decision_engine import enrich_observation
        _spec = state.spec
        if not _spec:
            _sp = Path(state.output_root) / "spec.json"
            if _sp.exists():
                _spec = json.loads(_sp.read_text(encoding="utf-8"))
        if _spec:
            obs = await enrich_observation(obs, _spec)
    except Exception:
        pass

    # 运行时图：给每个 gap_path 挂上“历史版本/修复”的确定性因果链。
    try:
        from src.layers.l3_decision.knowledge.query import (
            enrich_observation_history)

        obs = enrich_observation_history(obs, state.output_root)
    except Exception:
        pass

    # 事件驱动决策：发 COVERAGE_UPDATED → DecisionReactor → 读结果
    if rt.decision_reactor is not None:
        try:
            from src.layers.l2_orchestration.communication.verification_events import (
                publish_observation)
            await publish_observation(obs)
            action = rt.decision_reactor.last_action or rt.engine.decide(obs)
        except Exception:
            action = rt.engine.decide(obs)
    else:
        action = rt.engine.decide(obs)

    return {"pending_action": action.to_dict(),
            "coverage_history": [state.final_coverage]}


async def n_governor(state: PipelineState, config) -> Dict[str, Any]:
    """驾驭层：熔断 / 预算 / 干预。override 时改写动作，其余交由 router 决定。"""
    rt = _rt(config)
    action = state.action()
    govern = rt.governor.before_action(action.action_type)
    if govern.allowed:
        return {"governance_outcome": "proceed"}

    if (govern.intervention
            and govern.intervention.get("cmd") == "override_action"
            and govern.intervention.get("action_type")):
        override = Action(action_type=govern.intervention["action_type"], params={},
                          priority="HIGH", reason=f"人工 override: {govern.reason}")
        rt.governor.intervention.clear()
        return {"pending_action": override.to_dict(), "governance_outcome": "override"}

    logger.warning(f"驾驭层拦截: {govern.reason}")
    decision = rt.service._escalate_to_human(govern.reason, action.action_type)
    return {"governance_outcome": decision,   # retry / abort / 其它
            "human_escalation": decision,
            "phases": [{"name": "governor", "status": "blocked",
                        "reason": govern.reason}]}


async def n_governor_retry(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    try:
        rt.governor.breaker.reset((state.action() or Action("")).action_type)
    except Exception:
        pass
    return {}


async def n_record_decision(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    action = state.action()
    # 记住本轮动作，供下一轮记录成效
    _gr = [g.get("reason") for g in state.gaps
           if isinstance(g, dict) and g.get("reason")]
    _ud = [g.get("dimension") for g in state.gaps
           if isinstance(g, dict) and g.get("reason") == "unreachable" and g.get("dimension")]
    # **具名字典，不是元组**：下面 `run.py` 要取 `action` / `reason` /
    # `gap_reasons` / `unreachable_dims` / `source` 五项，元组一旦加字段就得
    # 同步改所有下标 —— 而漏改一处不会报错，只会**静默取错位**。
    # `source` 见 `Action.source`：它是 L4 按来源分桶统计的依据。
    rt.last_action = {
        "action": action.action_type,
        "reason": action.reason,
        "gap_reasons": _gr,
        "unreachable_dims": _ud,
        "source": getattr(action, "source", "rule") or "rule",
    }

    return {"last_action": action.to_dict(),
            "phases": [{"name": "decision", "status": "decision",
                        "action": action.action_type, "reason": action.reason}]}


