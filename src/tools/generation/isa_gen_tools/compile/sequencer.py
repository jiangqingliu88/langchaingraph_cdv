"""确定性随机 —— **全包唯一允许出现随机的地方**。

规矩（文档 §3.12.9 E5）：

    case_seed → 派生 seed = hash(case_seed ⊕ name)
    **新增张量不得改变既有张量的比特值**

后半句是这条规矩真正的分量所在。"用 seed 就能复现"很容易做到；
"**加一个对象而不动其它对象的取值**"才是难点 —— 它要求**每个可随机对象
各自一条独立的流**，而不是大家共用一个 RNG。

    共用 RNG：加一个对象 → 它后面的对象取值整体挪位 → 既有 case 全变
    各自开流：加一个对象 → 其它对象的流一个字节都不动

所以这个模块只做两件事：把 `(case_seed, name)` 折成一个派生 seed，
以及提供一个**不暴露全局状态**的 `Draw`。别的模块 `import random` 会被
`test_layering` 的源码守卫抓出来。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, TypeVar

from ..domain.dsl import derive_seed

T = TypeVar("T")


@dataclass
class Draw:
    """一个对象的取数器 —— 绑定到它自己的那条流。

    用法：

        draw = sequencer.draw("tensor:img")
        size = draw.choice([64, 128, 256])

    **不要把它传给别人复用**：一条流两处取数，两处就会互相影响，
    于是"改一处"会挪动另一处 —— E5 又破了。每个对象要 `draw()` 一次，
    这也正是 `Sequencer` 记账的原因。
    """

    name: str
    seed: int
    _rng: random.Random = field(repr=False, default=None)
    _count: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        if self._rng is None:
            self._rng = random.Random(self.seed)

    # ── 取数（都记数，便于"这个对象取了几次"可查） ──

    def choice(self, options: Sequence[T]) -> T:
        if not options:
            raise ValueError(f"{self.name} 没有可选项")
        self._count += 1
        return self._rng.choice(list(options))

    def weighted(self, weights: Dict[T, float]) -> T:
        """按权重抽一个键。权重全零时退化成均匀 —— 而不是崩。"""
        keys = list(weights)
        if not keys:
            raise ValueError(f"{self.name} 的权重表是空的")
        total = sum(max(0.0, float(w)) for w in weights.values())
        self._count += 1
        if total <= 0:
            return self._rng.choice(keys)
        point = self._rng.random() * total
        running = 0.0
        for key in keys:
            running += max(0.0, float(weights[key]))
            if point <= running:
                return key
        return keys[-1]

    def integer(self, low: int, high: int) -> int:
        self._count += 1
        return self._rng.randint(int(low), int(high))

    def chance(self, probability: float) -> bool:
        self._count += 1
        return self._rng.random() < float(probability)

    @property
    def draws(self) -> int:
        return self._count


class Sequencer:
    """一次编译的随机源中心 —— 每个对象一条流，按名字取。

    **同一个名字取两次会拿到两个独立但同 seed 的 `Draw`** —— 这是有意的：
    调用方不该靠着"拿到同一个对象"来共享状态。要连着取数就在一个
    `Draw` 上取完。
    """

    def __init__(self, case_seed: int) -> None:
        self.case_seed = int(case_seed)
        self._issued: List[str] = []

    def draw(self, name: str) -> Draw:
        """按名字派生一条流。名字就是派生的那个 `⊕ name`。"""
        if not name:
            raise ValueError("派生流必须给名字 —— 它就是 E5 里那个 ⊕ name")
        self._issued.append(name)
        return Draw(name=name, seed=derive_seed(self.case_seed, name))

    @property
    def issued(self) -> List[str]:
        """已经开出过哪些流（保序去重）—— 可复现链上的一环。"""
        seen: List[str] = []
        for name in self._issued:
            if name not in seen:
                seen.append(name)
        return seen

    def to_dict(self) -> Dict[str, Any]:
        return {"case_seed": self.case_seed, "streams": self.issued}
