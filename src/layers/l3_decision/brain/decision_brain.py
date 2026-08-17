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

from typing import Any, Dict, Optional

from src.layers.l3_decision.decision_engine import Action
from .state_encoder import encode_state
from .rl_policy import QLearningPolicy, SOFT_ACTIONS


class DecisionBrain:
    """规则 + RL 并行的决策大脑。"""

    def __init__(self, rule_engine, rl_policy: QLearningPolicy, target: float = 95.0):
        self.rule_engine = rule_engine
        self.rl_policy = rl_policy
        self.target = target
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
        if self.rl_policy.has_experience(state):
            action_type = self.rl_policy.select_action(state)
            return Action(
                action_type=action_type,
                params={},
                priority="MEDIUM",
                reason=f"RL 策略选择 {action_type}（状态 {state}，已学习 {self.rl_policy.q_entries_for(state)} 条）",
            )
        return self.rule_engine.decide(obs)

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
