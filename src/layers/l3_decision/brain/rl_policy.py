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


# RL 只学「覆盖率提升」的软动作。从动作全集派生，避免出现第二份会走样的清单：
#   - HARD_ACTIONS（编译失败/比对失败）由规则引擎确定性处理，RL 不参与
#   - TERMINAL_ACTIONS（CONVERGE）是达标终态，不属于 RL 动作空间
from src.layers.l3_decision.decision_engine import (
    ALL_ACTIONS, HARD_ACTIONS, TERMINAL_ACTIONS, rl_action,
)

#: RL 的动作空间。**「改 RTL」那一族折叠成一个条目**（`rl_action`）——
#: RL 学的是"这个状态下该不该动设计"，不是"这是哪一类 bug"（那一类由证据定，
#: 见 `classify_fix_bug`）。不折叠的话五个名字互相抢经验，还会让 RL 去**挑标签**。
SOFT_ACTIONS = list(dict.fromkeys(
    rl_action(a) for a in ALL_ACTIONS
    if a not in HARD_ACTIONS and a not in TERMINAL_ACTIONS))


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
        """读 Q 表 —— **动作名要归一**。

        动作改名之后（`REFACTOR_RTL` → `FIX_FUNCTIONAL_bug` 之类），老策略文件里
        存的是老名字。不归一的话那些经验既选不中（动作空间里没有老名字）、
        也永远读不回来 —— 而且 `stats()` 还会把它们算进"有经验"，看着有、用不上。
        """
        try:
            p = Path(self.json_path)
            if p.exists():
                from ..decision_engine import rl_action

                data = json.loads(p.read_text(encoding="utf-8"))
                self.q = {}
                for k, v in data.get("q", {}).items():
                    state, _, action = k.partition("::")
                    # `rl_action` = 归一 + 把"改 RTL 家族"折叠成一个名字 ——
                    # 老表里的 `REFACTOR_RTL`、以及曾经写进去的 `FIX_CDC_bug`
                    # 之类，都落回同一条经验（不然它们读不回来，等于白学）
                    self.q[(state, rl_action(action))] = v
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
