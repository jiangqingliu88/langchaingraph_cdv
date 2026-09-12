"""
Verification Event Bridge —— L1 执行结果 → 异步事件 → 订阅者响应

架构（对应「L1 是执行机器，结果是异步事件；Agent 订阅自己关心的信息」）：

  L1（RegressionRunner / coverage collect）
      │  publish
      ▼
  EventBus ── TEST_FINISHED / COVERAGE_UPDATED / BUG_DETECTED
      │
      ├── Knowledge Graph 订阅（世界模型更新：bin 命中 / bug / test 关联）
      └── （未来）Decision / Debug / Coverage Agent 订阅响应

这是把「拉取式同步」（coverage_agent.wait() → decision_agent.wait()）改成
「事件式异步」（L1 发事件 → 订阅者各自响应）的第一步。

用法:
    from src.layers.l2_orchestration.communication.verification_events import (
        register_verification_handlers, publish_coverage_updated, publish_bug_detected,
    )
    register_verification_handlers()          # 启动时注册一次（幂等）
    await publish_coverage_updated(module="gemm", coverage=95.0, gap="dma_boundary")
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.layers.l2_orchestration.communication.event_bus import get_event_bus, StandardEvent

_registered = False


# ═══════════════════════════════════════════════════════════════
# 发布辅助函数（L1 / Agent 调用）
# ═══════════════════════════════════════════════════════════════

async def publish_test_finished(testcase: str, status: str, log: str = "",
                                waveform: str = "", source: str = "l1_regression") -> None:
    await get_event_bus().publish(StandardEvent.TEST_FINISHED, {
        "testcase": testcase, "status": status, "log": log, "waveform": waveform,
    }, source=source)


async def publish_coverage_updated(module: str, coverage: float, gap: str = "",
                                   source: str = "l1_coverage") -> None:
    await get_event_bus().publish(StandardEvent.COVERAGE_UPDATED, {
        "module": module, "coverage": coverage, "gap": gap,
    }, source=source)


async def publish_bug_detected(signature: str, signal: str = "", category: str = "",
                               source: str = "debug_agent") -> None:
    await get_event_bus().publish(StandardEvent.BUG_DETECTED, {
        "signature": signature, "signal": signal, "category": category,
    }, source=source)


async def publish_observation(obs, module: str = "",
                              source: str = "run_closed_loop") -> None:
    """发布完整 Observation（含 gap_paths）作为 COVERAGE_UPDATED 事件。

    DecisionReactor 据此重建 Observation → decide → DECISION_MADE。
    """
    from dataclasses import asdict
    await get_event_bus().publish(StandardEvent.COVERAGE_UPDATED, {
        "module": module, "observation": asdict(obs),
    }, source=source)


# ═══════════════════════════════════════════════════════════════
# Knowledge Graph 世界模型订阅者（事件 → 图更新）
# ═══════════════════════════════════════════════════════════════

def register_verification_handlers() -> None:
    """注册 Knowledge Graph 世界模型订阅者（幂等）。"""
    global _registered
    if _registered:
        return
    bus = get_event_bus()

    @bus.on(StandardEvent.COVERAGE_UPDATED)
    async def _on_coverage_updated(event):
        """覆盖率更新 → 更新 KG 的 coverage_bin（gap 挂到 module）。"""
        try:
            from src.layers.l3_decision.knowledge.persistence import record_coverage_bins
            d = event.data
            gap = d.get("gap", "")
            module = d.get("module", "")
            if gap:
                await record_coverage_bins(
                    [{"name": gap, "metric": "gap", "module": module,
                      "hit": False, "misses": 1}],
                    run_id=event.trace_id or "")
        except Exception:
            pass

    @bus.on(StandardEvent.BUG_DETECTED)
    async def _on_bug_detected(event):
        """bug 检测 → 更新 KG 的 bug 节点（affects signal）。"""
        try:
            from src.layers.l3_decision.knowledge.persistence import record_bugs_and_fixes
            d = event.data
            await record_bugs_and_fixes(
                [{"bug_id": d.get("signature", ""),
                  "description": d.get("signature", ""),
                  "affected_signal": d.get("signal", ""),
                  "affected_feature": d.get("category", ""),
                  "severity": "P1"}],
                [], run_id=event.trace_id or "")
        except Exception:
            pass

    @bus.on(StandardEvent.TEST_FINISHED)
    async def _on_test_finished(event):
        """test 完成 → 留作 test→bin 关联的挂载点（当前只记录，不落库）。"""
        # 未来：test 结果关联到 KG 的 Test 节点 / test→bin 边
        pass

    _registered = True


class DecisionReactor:
    """L3 决策订阅者：订阅 COVERAGE_UPDATED → decide → 发布 DECISION_MADE。

    内部用 DecisionBrain（V3：规则硬失败 + RL 软决策并行），不再是纯规则引擎。
    RL Q 表持久化到 json_path（跨 run 学习）。

      L1 发 COVERAGE_UPDATED → DecisionReactor 决策 → 发 DECISION_MADE → 执行层订阅。
    """

    def __init__(self, target: float = 95.0, rl_json_path: str = None,
                 distilled_weights: dict = None):
        from src.layers.l3_decision.decision_engine import CoverageDrivenDecisionEngine
        from src.layers.l3_decision.brain.decision_brain import DecisionBrain
        from src.layers.l3_decision.brain.rl_policy import QLearningPolicy
        rule_engine = CoverageDrivenDecisionEngine(target=target)
        rl_policy = QLearningPolicy(json_path=rl_json_path)
        self.brain = DecisionBrain(rule_engine, rl_policy, target=target,
                                   distilled_weights=distilled_weights)
        self.last_action = None
        self._registered = False

    def register(self, bus) -> None:
        if self._registered:
            return
        self._registered = True

        @bus.on(StandardEvent.COVERAGE_UPDATED)
        async def _on_coverage_updated(event):
            from src.layers.l3_decision.decision_engine import Observation
            d = event.data
            obs_data = d.get("observation")
            if obs_data and isinstance(obs_data, dict):
                # 完整 Observation（含 gap_paths）→ 重建
                try:
                    obs = Observation(**obs_data)
                except Exception:
                    obs = None
            else:
                obs = None
            if obs is None:
                # fallback：summary（无 enrich 时）
                try:
                    cov = float(d.get("coverage", 0) or 0)
                except (TypeError, ValueError):
                    cov = 0.0
                obs = Observation(
                    coverage={"functional": cov},
                    gaps=[{"dimension": d.get("gap")}] if d.get("gap") else [],
                )
            action = self.brain.decide(obs)   # DecisionBrain：规则硬失败 + RL 软决策
            self.last_action = action
            await bus.publish(StandardEvent.DECISION_MADE, {
                "action_type": action.action_type,
                "reason": action.reason,
                "params": action.params,
            }, source="decision_reactor")


def register_decision_reactor(bus=None, target: float = 95.0,
                              rl_json_path: str = None,
                              distilled_weights: dict = None) -> DecisionReactor:
    """注册 L3 决策订阅者，返回 reactor（可读 last_action）。

    rl_json_path: RL Q 表持久化路径（跨 run 学习）；默认 None（内存，不持久化）。
    distilled_weights: L5 蒸馏出的动作权重（跨 run 成长）；默认 None（不启用）。
    """
    bus = bus or get_event_bus()
    reactor = DecisionReactor(target=target, rl_json_path=rl_json_path,
                              distilled_weights=distilled_weights)
    reactor.register(bus)
    return reactor
