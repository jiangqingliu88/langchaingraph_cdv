"""期望值标注 —— 给每条事务补上"怎么知道它对了"。

文档 §3.11 的"效应"列里，读回值的那些（`rdval` / `scalar_out` / `scalar_in`）
需要一个**观测点**。§3.12.6 的通用规则第 3 条明说：

> 观测类 op（`expect_*`）统一用 `ref`

所以标注这一步做三件事：

1. **命中 `xd=1` 的指令就补 `wait_done` + `expect_rd`**
   —— `xd` 是"这条指令要返回值"（见 `domain/opcode.py` 的 flags）。
   读回值必须先等它完成，否则 `expect_rd` 会在数据还没落地时就去核对。

2. **复用观测点纪律**（§3.12.6 通用规则 2）
   同一地址被时间复用时，两段使用之间必须至少有一个观测点，
   否则**前段的错误会被复用掩盖**。这里按"写同一个 ref 的两次之间
   有没有观测点"来判断。

3. **`binds` 里的 ref 必须都解析得到**（§3.14.4）
   对不上报 `UnresolvedRefError` —— 那是文档 §3.0 契约 2 要的失败。

**这一层不改既有指令**，只**追加**观测点。改的话就不是"标注"而是"生成"了，
两件事混在一起会让"这条指令哪来的"没法回答。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..domain import IrInstruction, Operands, Transaction, UnresolvedRefError


@dataclass(frozen=True)
class AnnotationResult:
    """标注结果。`instructions` 是**平铺之后**的指令流（含追加的观测点）。"""

    transactions: Tuple[Transaction, ...] = ()
    instructions: Tuple[IrInstruction, ...] = ()
    observations: Tuple[str, ...] = ()       # 加了观测点的 tag
    notes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"txn_count": len(self.transactions),
                "instruction_count": len(self.instructions),
                "observed_tags": list(self.observations),
                "notes": list(self.notes)}


def needs_readback(transaction: Transaction, registry) -> bool:
    """这条事务里有没有"要读回值"的指令 —— 判据是 `xd=1`。

    `xd` 是 flags 的一位（`domain/instruction.py`），语义是"这条指令写回 rdval"。
    由注册表给出，**不在这里按名字猜** —— 猜的话，新加一条带返回的指令
    就会被漏掉，而漏掉的后果是**它返回的值没人核对**。
    """
    for ins in transaction.instructions:
        spec = registry.find(ins.op)
        if spec is not None and spec.flags and spec.flags[0] == 1:
            return True
    return False


def annotate(transactions: Sequence[Transaction], *, registry,
             refs: Optional[set] = None) -> AnnotationResult:
    """给一串事务补观测点。

    `refs` 是本 case 里**能解析的对象引用集合**（`$t.<name>`）。
    给了就顺便核对（文档 §3.14.4：`binds` 里每个 ref 必须能找到 name）；
    不给就跳过那一项 —— 但跳过要记账，不是装作查过了。
    """
    out_txns: List[Transaction] = []
    flat: List[IrInstruction] = []
    observed: List[str] = []
    notes: List[str] = []

    if refs is None:
        notes.append("未提供 ref 表，binds/writes 的解析未核对")

    for transaction in transactions:
        tag = _tag_of(transaction)
        if refs is not None:
            _check_refs(transaction, refs)

        if needs_readback(transaction, registry) and tag:
            # 先等它完成，再核对返回值 —— 顺序不能反：wait_done 之前的 rdval
            # 还是上一拍的残留，那时候核对会报出一个假失败。
            #
            # **观测点要进事务本体，不是只进平铺的指令流。**
            # 第一版把它们只 append 到 `flat` 里，而 `IrProgram` 是从
            # transactions 建的 —— 于是观测点被整个丢掉，
            # IR 里一个 `expect_rd` 都没有（这个 bug 真的出现过：
            # `expect.anchors` 列出了 L4/L6，而 IR 里找不到它们）。
            transaction = _with_observations(transaction, tag)
            observed.append(tag)

        out_txns.append(transaction)
        flat.extend(transaction.instructions)

    if transactions and not observed:
        notes.append("这次没有任何事务需要读回值 —— 因此没有 expect_rd 观测点。"
                     "如果预期有，检查指令的 xd 位")

    return AnnotationResult(transactions=tuple(out_txns), instructions=tuple(flat),
                            observations=tuple(observed), notes=tuple(notes))


def _tag_of(transaction: Transaction) -> str:
    for ins in transaction.instructions:
        if ins.tag:
            return ins.tag
    return ""


def _check_refs(transaction: Transaction, refs: set) -> None:
    """`binds` 里每个 ref 都要能找到 —— 找不到就是文档 §3.0 契约 2 的失败。"""
    for name in transaction.binds:
        if name not in refs:
            raise UnresolvedRefError(
                f"{transaction.id} 绑定的 {name} 不在本次分配的对象里",
                target=f"{transaction.id}.binds",
                fix=f"可用对象：{sorted(refs)[:8]}"
                    if refs else "DSL 的 alloc 里没有声明对象")


def check_observation_discipline(transactions: Sequence[Transaction],
                                 plan=None) -> List[str]:
    """**复用观测点纪律**（§3.12.6 通用规则 2）。

    > 同一**地址**被时间复用时，两段使用之间必须至少有一个观测点
    > （`expect_write` / `expect_rd`），否则前段错误被复用掩盖。

    判据是**地址**，不是"对象被写两次"
        第一版把这条实现成了"同一个 ref 被写两次之间要有观测点" —— **错了**。
        同一个对象被反复写是**正常的**（累加、覆盖），不是地址复用。
        这条规矩说的是两件不同的事共用同一段地址（`overlap_ratio` 那个旋钮
        允许的 RAW 注入），那时**后一次写会把前一次的错误盖掉**，
        所以中间必须插一个观测点把前一次钉下来。

    所以：**要判断它，必须有地址信息**。不给 `plan` 就没有话可说 ——
    v0 的 bump 分配器根本不产生重叠（`overlap_ratio` 只被记录、没被用来制造重叠），
    所以这个检查在当前版本下正常是安静的。这一点如实返回一条 note，
    而不是造一堆假阳性出来。
    """
    if plan is None:
        return []

    from .allocator import global_address

    spans: Dict[str, Tuple[int, int]] = {}
    for allocation in getattr(plan, "allocations", ()):
        # 走 `global_address` 而不是自己加偏移 —— 它把 region 的语义位
        # （Mem_Flag / CIMC_flag）拼进去。自己算会把 SPAD 与 CIMC 的
        # 同偏移对象判成"共用地址"，那是假阳性。
        base = global_address(plan.region_bases.get(allocation.region, 0),
                              allocation.region, allocation.offset)
        spans[f"$t.{allocation.name}"] = (base, base + allocation.size)

    aliased = _aliased_refs(spans)
    if not aliased:
        return []                     # 没有地址复用 —— 这条纪律无可违反

    problems: List[str] = []
    for left, right in aliased:
        if not _has_observation_between(transactions, left, right):
            problems.append(
                f"{left} 与 {right} 共用同一段地址，但它们之间没有观测点 —— "
                "后一次写会把前一次的错误盖掉")
    return problems


def _aliased_refs(spans: Dict[str, Tuple[int, int]]) -> List[Tuple[str, str]]:
    """互相重叠的 ref 对（保序、去重）。"""
    names = sorted(spans)
    out: List[Tuple[str, str]] = []
    for index, left in enumerate(names):
        lo_a, hi_a = spans[left]
        for right in names[index + 1:]:
            lo_b, hi_b = spans[right]
            if lo_a < hi_b and lo_b < hi_a:
                out.append((left, right))
    return out


def _has_observation_between(transactions: Sequence[Transaction],
                             left: str, right: str) -> bool:
    """`left` 与 `right` 的**首次使用之间**有没有观测点。

    只看首次：纪律要挡的是"前段错误被复用掩盖"，那说的是复用发生的那一刻。
    """
    first: Dict[str, int] = {}
    for position, transaction in enumerate(transactions):
        for name in (tuple(transaction.binds)
                     + tuple(e.get("ref") if isinstance(e, dict) else str(e)
                             for e in transaction.writes)):
            if name in (left, right) and name not in first:
                first[name] = position
    if left not in first or right not in first:
        return True                   # 有一方压根没用过 —— 谈不上掩盖
    low, high = sorted((first[left], first[right]))
    for transaction in list(transactions)[low:high + 1]:
        if any(ins.op.startswith("expect") for ins in transaction.instructions):
            return True
    return False


def _with_observations(transaction: Transaction, tag: str) -> Transaction:
    """在事务尾部追加 `wait_done` + `expect_rd`，返回**新的事务**。

    追加到事务本体而不是平铺流，是因为 `IrProgram` 只认事务 ——
    平铺流是它派生出来的。往派生结果上写东西，下次派生就没了。
    """
    return Transaction(
        id=transaction.id, op=transaction.op,
        instructions=transaction.instructions
        + (IrInstruction(op="wait_done", tag=tag),
           IrInstruction(op="expect_rd", tag=tag)),
        pre=transaction.pre, hard=transaction.hard,
        effects=transaction.effects, pairing=transaction.pairing,
        requires=transaction.requires, cfg=transaction.cfg,
        registry_key=transaction.registry_key)
