"""
Decision Brain —— V3 决策大脑：规则（硬失败）+ RL（软决策）并行

把决策分成两类：
  硬失败（确定性，规则引擎处理）：编译错 / 比对错 / 环境失败
  软决策（学习，RL 策略处理）：覆盖率 gap 下「哪个动作提升最大」

学习信号：覆盖率 delta（本轮 functional - 上轮 functional）当 reward，
Q-learning 逐轮更新，跨 run 通过 JSON 持久化。

冷启动：状态无经验时回退规则引擎（含 V2 语义分支），保证初始决策质量；
有经验后 RL 接管软决策。

用法:
    from src.layers.l3_decision.brain.decision_brain import DecisionBrain
    brain = DecisionBrain(rule_engine, rl_policy, target=95.0)
    action = brain.decide(obs)   # 每轮调用一次，内部自动 learn + decide + 记忆
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.layers.l3_decision.decision_engine import Action
from .state_encoder import encode_state
from .rl_policy import QLearningPolicy, SOFT_ACTIONS


class DecisionBrain:
    """规则 + RL 并行的决策大脑。"""

    def __init__(self, rule_engine, rl_policy: QLearningPolicy, target: float = 95.0,
                 distilled_weights: Optional[Dict[str, float]] = None):
        self.rule_engine = rule_engine
        self.rl_policy = rl_policy
        self.target = target
        # 跨 run 成长（L5 蒸馏）：{action_type: weight}，weight>1 表示该动作
        # 历史改善率高。此前 DistillationOrchestrator.get_live_weights() **只有
        # CLI 展示会调用**，主循环从不读取，蒸馏结果等于白学。
        self.distilled_weights: Dict[str, float] = dict(distilled_weights or {})
        # 学习记忆（跨轮）
        self._prev_state: Optional[str] = None
        self._prev_action: Optional[str] = None
        self._prev_coverage: Optional[float] = None
        self._reward_ema: Optional[float] = None   # 奖励平滑（EMA）

    def decide(self, obs) -> Action:
        cov = obs.coverage or {}
        try:
            functional = float(cov.get("functional", 0) or 0)
        except (TypeError, ValueError):
            functional = 0.0
        state = encode_state(obs, self.target)

        # ── 学习：上轮动作 + 本轮覆盖率增量（平滑）= reward ──
        if self._prev_state is not None and self._prev_action is not None \
                and self._prev_coverage is not None:
            raw_reward = functional - self._prev_coverage
            reward = self._smooth_reward(raw_reward)
            self.rl_policy.learn(self._prev_state, self._prev_action, reward, state)

        # ── 决策 ──
        action = self._decide_inner(obs, state)

        # ── 记忆 ──
        self._prev_state = state
        self._prev_action = action.action_type if action else None
        self._prev_coverage = functional

        return action

    def _decide_inner(self, obs, state: str) -> Action:
        # 1. 硬失败 → 规则引擎（确定性）
        if obs.compile_error or obs.model_mismatch or obs.failed_tests:
            return self.rule_engine.decide(obs)

        # 2. 达标 → CONVERGE（规则，非 RL——收敛是确定性的终态）
        cov = obs.coverage or {}
        try:
            functional = float(cov.get("functional", 0) or 0)
        except (TypeError, ValueError):
            functional = 0.0
        if functional >= self.target:
            return Action(
                action_type="CONVERGE",
                params={"final_coverage": functional},
                priority="LOW",
                reason=f"覆盖率 {functional}% ≥ {self.target}%，收敛",
            )

        # 3. 软决策 → RL（有经验）或规则（冷启动）
        rule_action = self.rule_engine.decide(obs)
        if self.rl_policy.has_experience(state):
            action_type = self.rl_policy.select_action(state)
            if action_type == rule_action.action_type:
                # RL 与规则选到同一个动作：直接用规则的结果，params 是它算好的
                rule_action.reason += f"（RL 与规则一致，状态 {state}）"
                return rule_action
            # RL 覆盖规则。此前这里 params={}，导致 RELAX_CONSTRAINT /
            # GENERATE_DIRECTED_TEST 带着**空 gaps** 到达执行层——
            # 「放宽约束」实际什么都没放宽，「定向补测」也没指定目标。
            # RL 只学「选哪个动作」，参数必须由我们补齐。
            return Action(
                action_type=action_type,
                params=self._params_for(action_type, obs, rule_action),
                priority="MEDIUM",
                reason=(f"RL 覆盖规则：{rule_action.action_type} → {action_type}"
                        f"（状态 {state}，已学习 {self.rl_policy.q_entries_for(state)} 条）"),
            )

        # 冷启动（RL 无经验）：先看有没有跨 run 蒸馏出的动作权重
        pick = self._pick_by_weight(obs)
        if pick and pick != rule_action.action_type:
            return Action(
                action_type=pick,
                params=self._params_for(pick, obs, rule_action),
                priority="MEDIUM",
                reason=(f"蒸馏权重优先：{rule_action.action_type} → {pick}"
                        f"（跨 run 学习：该动作历史改善率高，权重 "
                        f"{self.distilled_weights.get(pick, 1.0):.2f}）"),
            )
        return rule_action

    def _pick_by_weight(self, obs: Any) -> Optional[str]:
        """按蒸馏权重挑一个**观测支持**的动作；无权重或无适用动作时返回 None。

        关键约束：只在观测确实支持该动作时才采纳权重——否则权重再高也可能
        选出一个无依据的动作（比如没有任何 gap 却去 RELAX_CONSTRAINT）。
        """
        if not self.distilled_weights:
            return None

        gaps = [g for g in (getattr(obs, "gaps", None) or []) if isinstance(g, dict)]
        reasons = {g.get("reason") for g in gaps}

        supported: List[str] = []
        if gaps and "constraint" in reasons:
            supported.append("RELAX_CONSTRAINT")
        if gaps:
            supported.append("GENERATE_DIRECTED_TEST")
        if (getattr(obs, "failed_tests", None)
                or getattr(obs, "dead_code_modules", None)):
            supported.append("REFACTOR_RTL")
        supported.append("EXPAND_SEEDS")  # 扩种无前置条件，总是可用

        candidates = [a for a in supported if a in self.distilled_weights]
        if not candidates:
            return None
        return max(candidates, key=lambda a: self.distilled_weights.get(a, 1.0))

    def _params_for(self, action_type: str, obs: Any, rule_action: Action) -> Dict[str, Any]:
        """为 RL 选中的动作补齐参数。

        RL 的动作空间只有动作名，没有参数；参数得从观测或规则结果里取，
        否则下游拿到空 gaps。同动作时优先复用规则算好的 params——**但只在
        动作相同时**，否则会把别的动作的参数（比如 gaps）塞给不认它的动作。
        """
        if rule_action.action_type == action_type and rule_action.params:
            return dict(rule_action.params)

        gaps = getattr(obs, "gaps", None) or []
        if action_type in ("RELAX_CONSTRAINT", "GENERATE_DIRECTED_TEST"):
            return {"gaps": list(gaps)}
        if action_type == "REFACTOR_RTL":
            return {"failed_tests": list(getattr(obs, "failed_tests", None) or [])}
        if action_type == "EXPAND_SEEDS":
            # 扩种数量取规则引擎的缺省，与 decide() 的 seed_expand_count 保持一致
            return {"count": getattr(self.rule_engine, "seed_expand_count", 1000)}
        return {}

    def _smooth_reward(self, raw_reward: float) -> float:
        """EMA 平滑奖励：覆盖率提升非线性（前涨后滞），单轮 delta 噪声大，平滑降噪。"""
        if self._reward_ema is None:
            self._reward_ema = raw_reward
        else:
            self._reward_ema = 0.5 * raw_reward + 0.5 * self._reward_ema
        return self._reward_ema

    def stats(self) -> Dict[str, Any]:
        return {"rl": self.rl_policy.stats(),
                "prev_state": self._prev_state, "prev_action": self._prev_action}
