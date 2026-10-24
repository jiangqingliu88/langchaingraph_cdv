"""IR 程序 —— 一次编译的产物，以及那条**按设计不会触发**的兜底断言。

`IrProgram` 由 `Transaction` 组成，不是由散指令组成。这挡住了绝大部分破坏配对
的路径：想放一条 `gemm_drv_xn`，就得先造一个带 `gemm_out_org_pre_xn` 的事务。

那为什么还要有 `verify_pairing()`？
    因为有**一条**绕过类型的缝：`from_transactions` 之外，还有
    `IrProgram.from_instructions()` —— 从裸 dict 反序列化一份历史 IR。
    那份 IR 可能来自别的工具、可能被人手改过、可能是上一版生成器留的。

    所以这条断言不是"检查我们的生成逻辑"，是**守着那道门**。
    有测试专门造一次裸 dict 让它响（`test_domain.py`），证明它活着 ——
    一条永远跑不到的断言和没有断言是一回事，区别只在于前者会让人误以为有保护。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .errors import PairingError
from .instruction import IrInstruction
from .transaction import Transaction


@dataclass(frozen=True)
class IrProgram:
    """一次编译产出的 IR 程序。

    `transactions` 是**真相**；`instructions` 是把它摊平的结果。
    摊平是单向的（事务 → 指令），所以不存在"摊平之后再改一条"这种可能。
    """

    transactions: Tuple[Transaction, ...] = ()
    seed: Optional[int] = None
    name: str = ""
    isa_rev: str = ""
    target: str = ""
    memmap_version: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    notes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.verify_pairing()

    # ── 摊平 ──

    @property
    def instructions(self) -> Tuple[IrInstruction, ...]:
        """按事务顺序摊成指令流 —— 给执行器 / 编码器用。"""
        out: List[IrInstruction] = []
        for txn in self.transactions:
            out.extend(txn.instructions)
        return tuple(out)

    @property
    def op_sequence(self) -> Tuple[str, ...]:
        return tuple(ins.op for ins in self.instructions)

    def __len__(self) -> int:
        return len(self.transactions)

    # ── 兜底 ──

    def verify_pairing(self) -> None:
        """配对组必须闭合 —— 只对**从裸 dict 进来的**那些有意义。

        判据：声明了配对的每个事务，它的配对组里两条指令都在。
        `Transaction.__post_init__` 已经查过一遍；这里再查是因为
        `from_instructions` 会把裸指令**重新包成单指令事务**，
        那些事务的配对信息是反推出来的、可能不闭合。
        """
        offenders: List[str] = []
        for txn in self.transactions:
            if not txn.pairing.requires_group:
                continue
            ops = {ins.op for ins in txn.instructions}
            if len(ops) < 2:
                offenders.append(f"{txn.id}({sorted(ops)})")
        if offenders:
            raise PairingError(
                "配对组不闭合："
                + "、".join(offenders[:5])
                + (f"（共 {len(offenders)} 处）" if len(offenders) > 5 else ""),
                target=offenders[0],
                fix="这通常意味着 IR 是从裸 dict 反序列化来的、或被人手改过。"
                    "生成路径（compile/templates.py）不可能产出这种 IR")

    # ── 构造 ──

    @classmethod
    def from_transactions(cls, transactions: Sequence[Transaction], **meta: Any) -> "IrProgram":
        """正常路径：由事务组装。"""
        return cls(transactions=tuple(transactions), **meta)

    @classmethod
    def from_instructions(cls, instructions: Iterable[IrInstruction],
                          registry: Any = None, **meta: Any) -> "IrProgram":
        """**逃生口**：从裸指令回读。

        每条指令重新包成一个单指令事务。如果这条指令按注册表是需要配对的，
        包出来的事务就不闭合 —— `verify_pairing()` 会当场响。
        这正是我们想要的：**回读一份缺了 pre 的历史 IR，要在读的时候炸，
        不要等到仿真里表现成器件行为异常。**
        """
        from .transaction import Pairing

        transactions: List[Transaction] = []
        for index, ins in enumerate(instructions):
            pairing = Pairing()
            if registry is not None:
                spec = registry.find(ins.op)
                if spec is not None and spec.pairing.value != "none":
                    pairing = Pairing(kind=spec.pairing,
                                      group_id=f"{ins.op}#{index}")
            transactions.append(Transaction(
                id=f"{ins.op}#{index}", op=ins.op, instructions=(ins,),
                pairing=pairing))
        return cls(transactions=tuple(transactions), **meta)

    # ── 落盘 ──

    def to_dict(self) -> Dict[str, Any]:
        """`seq.ir.json` 的形状（文档 §3.6）。

        顶层是**指令流**而不是事务树：TB 执行器与 ISS 消费的都是平铺的指令序，
        没有谁需要按事务分组。事务的语义（配对 / 硬约束 / 效应）在
        `manifest` 里留一份，需要的时候查得到。
        """
        return {
            "name": self.name,
            "isa_rev": self.isa_rev,
            "target": self.target,
            "seed": self.seed,
            "memmap_version": self.memmap_version,
            "instructions": [ins.to_dict() for ins in self.instructions],
            "transactions": [t.to_dict() for t in self.transactions],
            "meta": dict(self.meta),
            "notes": list(self.notes),
        }

    def summary(self) -> Dict[str, Any]:
        """给人看的一行概览。"""
        return {
            "name": self.name,
            "seed": self.seed,
            "txn_count": len(self.transactions),
            "instruction_count": len(self.instructions),
            "op_histogram": _histogram(self.op_sequence),
        }


def _histogram(names: Sequence[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for name in names:
        out[name] = out.get(name, 0) + 1
    return dict(sorted(out.items()))
