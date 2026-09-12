"""
RL Policy —— 轻量表格 Q-learning（V3 决策学习层的动作选择器）

V3 的 RL 只负责「软决策」（覆盖率优化），不管「硬失败」（编译错/比对错/环境失败，
那些由规则引擎确定性处理）。所以动作空间是 4 个软动作
（CONVERGE 是达标时的确定性终态，不属于 RL 动作空间）：

    SOFT_ACTIONS = [EXPAND_SEEDS, REFACTOR_RTL, RELAX_CONSTRAINT,
                    GENERATE_DIRECTED_TEST]

Q-learning 核心：
    Q[s,a] += α * ( reward + γ * max_a' Q[s',a'] - Q[s,a] )
    reward = 覆盖率 delta（动作前后的 functional 覆盖率变化）

ε-greedy 探索：探索（随机动作）vs 利用（最大 Q 动作）平衡。

持久化：JSON 文件（跨 run 学习），路径可配（默认不持久化，纯内存）。

这是「先跑通闭环」的轻量版；验证收益后可升级 DQN（神经网络近似 Q 函数）。

用法:
    from src.layers.l3_decision.brain.rl_policy import QLearningPolicy
    policy = QLearningPolicy(json_path=".signoffai/rl_policy.json")
    action = policy.select_action(state)
    policy.learn(state, action, reward=+3.0, next_state=next_state)
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# RL 只学「覆盖率提升」的软动作；CONVERGE 是达标时的确定性规则，不属于 RL 动作空间
SOFT_ACTIONS = ["EXPAND_SEEDS", "REFACTOR_RTL", "RELAX_CONSTRAINT",
                "GENERATE_DIRECTED_TEST"]


class QLearningPolicy:
    """表格 Q-learning 策略。"""

    def __init__(self, epsilon: float = 0.1, alpha: float = 0.3, gamma: float = 0.9,
                 json_path: str = None, seed: int = 0):
        self.q: Dict[Tuple[str, str], float] = {}
        self.epsilon = epsilon
        self.alpha = alpha
        self.gamma = gamma
        self.json_path = json_path
        self._rng = random.Random(seed)
        if json_path:
            self._load()

    # ── 动作选择（ε-greedy）──
    def select_action(self, state: str, available: List[str] = None) -> str:
        actions = list(available or SOFT_ACTIONS)
        if not actions:
            return "CONVERGE"
        if self._rng.random() < self.epsilon:
            return self._rng.choice(actions)  # 探索
        # 利用：最大 Q 动作（平局随机）
        best_value = max((self.q.get((state, a), 0.0) for a in actions), default=0.0)
        best = [a for a in actions if self.q.get((state, a), 0.0) == best_value]
        return self._rng.choice(best)

    # ── 学习（Q 更新）──
    def learn(self, state: str, action: str, reward: float, next_state: str) -> float:
        old = self.q.get((state, action), 0.0)
        best_next = max((self.q.get((next_state, a), 0.0) for a in SOFT_ACTIONS), default=0.0)
        new = old + self.alpha * (reward + self.gamma * best_next - old)
        self.q[(state, action)] = new
        if self.json_path:
            self._save()
        return new

    # ── 持久化 ──
    def _load(self):
        try:
            p = Path(self.json_path)
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                self.q = {tuple(k.split("::")): v for k, v in data.get("q", {}).items()}
        except Exception:
            pass

    def _save(self):
        try:
            p = Path(self.json_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {"q": {"::".join(k): v for k, v in self.q.items()}}
            p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def has_experience(self, state: str) -> bool:
        """该状态是否有 Q 经验（冷启动判断）。"""
        return any(s == state for s, _ in self.q)

    def q_entries_for(self, state: str) -> int:
        """该状态的 Q 条目数。"""
        return sum(1 for s, _ in self.q if s == state)

    def stats(self) -> Dict[str, int]:
        return {"states": len({s for s, _ in self.q}),
                "q_entries": len(self.q)}
