"""L3 编排 —— 把求解出来的一串事务排成**时间窗**（文档 §3.9 的 L3）。

    epoch 1 | txn txn txn | 同步点 | epoch 2 | txn txn | 同步点 | …

三个旋钮，都在 `orchestration` / `intent` 里：

    orchestration.epochs                 分几段
    orchestration.epoch_boundary_sync    `random` / `always` / `never`
    intent.fence_every_n_epochs          每隔几段插一条 NoC fence（0 = 不插）

**为什么同步点是编排的事，不是求解的事**
    "哪类事务更常出现"（L2）和"在哪切一刀"（L3）是两个正交的问题。
    混在一起的话，调 hazard 密度会顺带动了同步点的位置 —— 而那两个旋钮
    在文档里是分开的（§3.15 的缺口→偏置映射表列的是 hazard/mcast/fence 三项）。

同步点插什么
    文档 §3.11 有两条同步事务：
      · `sync_txn`      本核全部 Master 等齐（域内同步）
      · `noc_fence_txn` 等齐在飞 NoC 事务（域间同步）
    epoch 边界插前者（切时间窗），`fence_every_n_epochs` 插后者（周期性收口）。
    两者都靠 `wait_done` 的 tag 锚定 —— 所以编排返回的是**带上 tag 的指令流**，
    不是裸事务列表。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..domain import SolverError, Transaction, TransactionRegistry
from ..domain.dsl import DslDocument
from .sequencer import Draw, Sequencer


@dataclass(frozen=True)
class Epoch:
    """一个时间窗。`transactions` 是窗内的事务，保序。"""

    index: int
    transactions: Tuple[Transaction, ...] = ()
    note: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.transactions

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index,
                "txn_count": len(self.transactions),
                "ops": [t.op for t in self.transactions],
                "note": self.note}


@dataclass(frozen=True)
class Schedule:
    """编排结果 —— 一串 epoch + 它们之间的同步点。"""

    epochs: Tuple[Epoch, ...] = ()
    sync_points: Tuple[int, ...] = ()       # 在第几个 epoch **之后**插同步
    fence_points: Tuple[int, ...] = ()      # 在第几个 epoch 之后插 NoC fence
    notes: Tuple[str, ...] = ()

    @property
    def transactions(self) -> Tuple[Transaction, ...]:
        return tuple(t for epoch in self.epochs for t in epoch.transactions)

    def __len__(self) -> int:
        return len(self.epochs)

    def to_dict(self) -> Dict[str, Any]:
        return {"epoch_count": len(self.epochs),
                "txn_count": len(self.transactions),
                "sync_after": list(self.sync_points),
                "fence_after": list(self.fence_points),
                "epochs": [e.to_dict() for e in self.epochs],
                "notes": list(self.notes)}


def split_epochs(transactions: Sequence[Transaction], *, epochs: int) -> List[Epoch]:
    """把一串事务切成 `epochs` 段。

    **余数往前放**：10 条分 3 段是 4/3/3 而不是 3/3/4 —— 第一段是"起手"，
    给它多一点能让后面的段更均衡（方差小），也让"起点"永远非空。
    `epochs` 大于事务数时，后面的段是空的 —— 空段是合法的（它表示"这一窗没排到活"），
    但**不静默**：`plan_epochs` 会把它记成 note。
    """
    if epochs < 1:
        raise SolverError(f"epochs 至少是 1，拿到 {epochs}", target="orchestration.epochs")
    total = len(transactions)
    base, extra = divmod(total, epochs)
    out: List[Epoch] = []
    cursor = 0
    for index in range(epochs):
        size = base + (1 if index < extra else 0)
        out.append(Epoch(index=index, transactions=tuple(transactions[cursor:cursor + size])))
        cursor += size
    return out


def plan_epochs(dsl: DslDocument, transactions: Sequence[Transaction], *,
                registry: TransactionRegistry,
                sequencer: Sequencer) -> Schedule:
    """切时间窗 + 定同步点。

    同步策略（`epoch_boundary_sync`）：
      · `always` 每个 epoch 边界都插 `sync_txn`
      · `never`  一个都不插
      · `random` 每个边界各掷一次（用**编排自己的流**，与事务选择无关）
    """
    epochs = split_epochs(transactions, epochs=dsl.orchestration.epochs)
    for epoch in epochs:
        if epoch.is_empty:
            # 空段不是错误，但要说出来 —— 它意味着 orchestration.epochs
            # 比实际生成的事务数还多
            continue

    notes: List[str] = []
    empty = [e.index for e in epochs if e.is_empty]
    if empty:
        notes.append(f"{len(empty)} 个 epoch 是空的（epochs="
                     f"{dsl.orchestration.epochs} 多于生成的事务数）")

    roll = sequencer.draw("epoch:sync")
    strategy = (dsl.orchestration.epoch_boundary_sync or "random").strip().lower()
    boundaries = list(range(len(epochs) - 1))        # 最后一个 epoch 之后不插

    if strategy == "always":
        sync_points = boundaries
    elif strategy == "never":
        sync_points = []
    elif strategy == "random":
        sync_points = [i for i in boundaries if roll.chance(0.5)]
    elif strategy == "sync":
        # 文档 §3.10.2 的例子写的就是 `sync` —— 与 `always` 同义，
        # 但名字不同，所以显式认一下而不是当成未知策略
        sync_points = boundaries
    else:
        raise SolverError(
            f"不认识的 epoch_boundary_sync={dsl.orchestration.epoch_boundary_sync!r}",
            target="orchestration.epoch_boundary_sync",
            fix="可选：random / always / never / sync")

    every = int(dsl.intent.fence_every_n_epochs or 0)
    fence_points: List[int] = []
    if every > 0:
        fence_points = [i for i in boundaries if (i + 1) % every == 0]
        if not fence_points and boundaries:
            notes.append(f"fence_every_n_epochs={every} 但只有 {len(epochs)} 个 epoch，"
                         "一次都没触发")

    if dsl.orchestration.epoch_boundary_sync == "random" and not sync_points and boundaries:
        notes.append("随机同步点这次一个都没掷中（边界的 50% 概率）")

    return Schedule(epochs=tuple(epochs), sync_points=tuple(sync_points),
                    fence_points=tuple(fence_points), notes=tuple(notes))


#: 同步点插哪个事务 —— 域内用 sync，域间用 noc_fence（见模块头）
EPOCH_SYNC_TXN = "sync_txn"
EPOCH_FENCE_TXN = "noc_fence_txn"
