"""事务 —— **随机化的最小单元**，也是"配对不可能被破坏"这件事的落点。

为什么最小单元不是指令（文档 §3.9）
    HM057 的 ISA 有事务结构：`group_mask → cfg → [pre] → drv` 是强配对，
    `tld` 前必须有 `tld_cfg`，`gemm` 前必须有 `gemm_out_org_pre`。
    **以单条指令为随机单元会高概率产出非法序列** —— 而非法序列漏进仿真，
    表现得像器件行为异常，排查成本极高。

    所以生成器在这条路上一开始就走不通的地方，就不要让它走通：

        ✗ 先生成指令列表，再检查配对是否完整
        ✓ 让"单独一条 gemm_drv_xn"根本造不出来

    下面 `Transaction.instructions` 是**不可分割的有序元组**。IR 程序由
    `Transaction` 组装，没有任何 API 能往程序里塞一条裸指令。配对不是被
    "检查"的，是被**类型**挡住的。

    那 `program.py` 里为什么还有一条 `PairingError` 断言？因为有一条逃生口：
    从裸 dict 反序列化一份历史 IR（那份 IR 可能来自别的工具、手工编辑过）。
    那条断言只为逃生口存在，有测试专门造一次裸 dict 证明它是活的。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .errors import PairingError, RegistryError, WhitelistError
from .instruction import IrInstruction
from .opcode import OpRegistry, PairingKind

# ═══════════════════════════════════════════════════════════════
# 事务描述符的三块（文档 §3.11 的列）
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class HardConstraint:
    """硬约束 —— **L0 层，永不放宽**（文档 §3.15 规则 2）。

    形如"32bit 对齐，仅 SPAD"、"恰好选中 2 核"、"256bit 对齐"。
    缺口回灌只允许调 L2 意图旋钮，**不允许碰这里** —— 所以它单独成一个类型，
    而不是散在生成器各处的 `if` 里。
    """

    kind: str                      # align / region / mask_cardinality / pairing …
    target: str = ""
    param: Any = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out = {"kind": self.kind}
        if self.target:
            out["target"] = self.target
        if self.param is not None:
            out["param"] = self.param
        if self.note:
            out["note"] = self.note
        return out


@dataclass(frozen=True)
class Effect:
    """效应 —— 这条事务对世界做了什么（文档 §3.11 的"效应"列）。

    生成器靠它做两件事：推导 `binds/writes`，以及判断"用了这个张量之后
    它变成什么状态"（后续事务的前置条件要用）。
    """

    kind: str                      # write / read / broadcast / reduce / move …
    target: str = ""
    span: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out = {"kind": self.kind}
        if self.target:
            out["target"] = self.target
        if self.span:
            out["span"] = self.span
        if self.note:
            out["note"] = self.note
        return out


@dataclass(frozen=True)
class PreStep:
    """事务里先于 drv 的那一步。

    `op` 是具体指令名；`fills` 说明它要填哪些字段（例如 `die_cluster_pre_xn`
    预装高位地址）。它**不是**可选的装饰 —— 在 `Transaction` 里它就是
    `instructions` 元组的前几项，去不掉。
    """

    op: str
    fills: Tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out = {"op": self.op}
        if self.fills:
            out["fills"] = list(self.fills)
        if self.note:
            out["note"] = self.note
        return out


@dataclass(frozen=True)
class Pairing:
    """配对关系 —— 值对象，不是检查逻辑。

    `group_id` 让"这一组必须在一起"可被机械核对；
    `adjacency="strict"` 表达 `noc_pair_txn` 那种"中途不允许插入其他指令"。
    """

    kind: PairingKind = PairingKind.NONE
    group_id: str = ""
    adjacency: str = ""            # "" | "strict"

    @property
    def requires_group(self) -> bool:
        return self.kind is not PairingKind.NONE

    def to_dict(self) -> Dict[str, Any]:
        out = {"kind": self.kind.value}
        if self.group_id:
            out["group_id"] = self.group_id
        if self.adjacency:
            out["adjacency"] = self.adjacency
        return out


# ═══════════════════════════════════════════════════════════════
# 事务
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Transaction:
    """一次事务 —— 生成器能造出的最小东西。

    `instructions` 是**有序不可分的元组**：pre 在前、drv 在后，一起去一起走。
    这是"配对由类型保证"的实现点 —— 想造一条孤立的 `gemm_drv_xn`，
    就得先造一个 `Transaction`，而它必然带着自己的 `gemm_out_org_pre_xn`。
    """

    id: str
    op: str                                   # 事务的主指令（drv 那条）
    instructions: Tuple[IrInstruction, ...] = ()
    pre: Tuple[PreStep, ...] = ()
    hard: Tuple[HardConstraint, ...] = ()
    effects: Tuple[Effect, ...] = ()
    pairing: Pairing = field(default_factory=Pairing)
    requires: Tuple[str, ...] = ()            # 前置条件（人读的）
    cfg: str = ""                             # 需要先配的 cfg 表
    registry_key: str = ""                    # 指向 txn.registry.json 的那一行

    def __post_init__(self) -> None:
        if not self.id:
            raise WhitelistError("事务缺 id", fix="每个事务要有稳定标识")
        if not self.instructions:
            raise PairingError(
                f"事务 {self.id} 没有任何指令",
                target=self.id,
                fix="事务至少要有一条指令；空的『事务』不是事务")
        self._check_pairing_closed()

    def _check_pairing_closed(self) -> None:
        """配对组必须**整个**落在这一个事务里。

        正常路径到不了这里（类型已经挡住）。它拦的是"有人手工拼了个
        `Transaction`，只放了 pre 或只放了 drv"——那是唯一能绕过类型的缝。
        """
        if not self.pairing.requires_group:
            return
        ops = {ins.op for ins in self.instructions}
        if len(ops) < 2:
            raise PairingError(
                f"事务 {self.id} 声明了 {self.pairing.kind.value} 配对，"
                f"但只含 {len(ops)} 条指令：{sorted(ops)}",
                target=self.id,
                fix="配对组的两条指令必须同属一个事务（见 transaction.py 模块头）")

    # ── 派生 ──

    @property
    def op_names(self) -> Tuple[str, ...]:
        return tuple(ins.op for ins in self.instructions)

    @property
    def binds(self) -> Tuple[str, ...]:
        """整个事务读的张量 ref（去重保序）。"""
        seen: List[str] = []
        for ins in self.instructions:
            for ref in ins.binds:
                if ref not in seen:
                    seen.append(ref)
        return tuple(seen)

    @property
    def writes(self) -> Tuple[Any, ...]:
        seen: List[Any] = []
        for ins in self.instructions:
            for ref in ins.writes:
                key = ref if isinstance(ref, str) else tuple(sorted(ref.items()))
                if key not in [s if isinstance(s, str) else tuple(sorted(s.items()))
                               for s in seen]:
                    seen.append(ref)
        return tuple(seen)

    def with_tag(self, tag: str) -> "Transaction":
        return Transaction(
            id=self.id, op=self.op,
            instructions=tuple(ins.with_tag(tag) for ins in self.instructions),
            pre=self.pre, hard=self.hard, effects=self.effects,
            pairing=self.pairing, requires=self.requires, cfg=self.cfg,
            registry_key=self.registry_key)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"id": self.id, "op": self.op,
                               "instructions": [i.to_dict() for i in self.instructions]}
        if self.pre:
            out["pre"] = [p.to_dict() for p in self.pre]
        if self.hard:
            out["hard"] = [h.to_dict() for h in self.hard]
        if self.effects:
            out["effects"] = [e.to_dict() for e in self.effects]
        if self.pairing.requires_group or self.pairing.adjacency:
            out["pairing"] = self.pairing.to_dict()
        if self.requires:
            out["requires"] = list(self.requires)
        if self.cfg:
            out["cfg"] = self.cfg
        return out


# ═══════════════════════════════════════════════════════════════
# 构造事务的唯一入口
# ═══════════════════════════════════════════════════════════════

def build_transaction(*, txn_id: str, op: str, instructions: Sequence[IrInstruction],
                      registry: Optional[OpRegistry] = None,
                      registry_key: str = "", cfg: str = "",
                      requires: Sequence[str] = (),
                      pre: Sequence[PreStep] = (),
                      hard: Sequence[HardConstraint] = (),
                      effects: Sequence[Effect] = ()) -> Transaction:
    """把一组指令包成一个事务 —— **生成器造指令的唯一入口**。

    它比直接 `Transaction(...)` 多做一件事：**按注册表核对配对**。
    注册表说 `gemm_drv_xn` 是 `PRE_DRV`，那这一组里就必须有配对的 pre；
    说 `noc_drv_dst_xn` 是 `DST_SRC`，就必须有对应的 src。

    调用方（`compile/templates.py`）按事务描述符组装，所以这一步是"白拿"的
    一致性检查 —— 而不是靠模板作者记得写对。
    """
    instruction_tuple = tuple(instructions)
    pairing = Pairing()
    if registry is not None:
        pairing = _derive_pairing(op, instruction_tuple, registry)

    return Transaction(
        id=txn_id, op=op, instructions=instruction_tuple, pre=tuple(pre),
        hard=tuple(hard), effects=tuple(effects), pairing=pairing,
        requires=tuple(requires), cfg=cfg, registry_key=registry_key)


#: 配对形态 → 该配对组里另一条的"角色"
_PAIRED_ROLE = {
    PairingKind.PRE_DRV: "pre",
    PairingKind.DST_SRC: "dst/src",
}


def _derive_pairing(op: str, instructions: Sequence[IrInstruction],
                    registry: OpRegistry) -> Pairing:
    """从注册表推这次事务的配对形态，并当场核对它是闭合的。

    **扫的是整组，不是只看主指令。** 早先只看 `op`（组里最后一条），
    于是 `noc_pair_txn`（dst + src）漏了判 —— 它的主指令是 `noc_drv_src_xn`，
    而注册表把配对标在 `noc_drv_dst_xn` 上。一条事务里只要**有**一条指令
    声明了配对，整组就受那个约束。

    注册表说需要配对，而这一组里只有它一条 → `WhitelistError`。
    报在这里而不是等到仿真：**这是"组合白名单"那条规格的落点**（§3.11 通用规则 2）。
    """
    names = [ins.op for ins in instructions]
    paired = [(name, spec) for name in names
              if (spec := registry.find(name)) is not None
              and spec.pairing is not PairingKind.NONE]
    if not paired:
        return Pairing()

    # 一条事务里出现两种配对形态是没有意义的 —— 报出来，别挑一个
    kinds = {spec.pairing for _, spec in paired}
    if len(kinds) > 1:
        raise WhitelistError(
            f"事务里出现了两种配对形态：{[k.value for k in kinds]}",
            target=op, fix="一条事务只应有一种配对形态")

    kind = kinds.pop()
    if len(set(names)) < 2:
        raise WhitelistError(
            f"{op} 需要 {kind.value} 配对，但这一组里只有它自己",
            target=op,
            fix=f"按注册表补上配对的 {_PAIRED_ROLE.get(kind, '另一条')} 指令；"
                f"模板见 compile/templates.py")

    return Pairing(kind=kind, group_id=f"{op}#{names[0]}",
                   adjacency="strict" if kind is PairingKind.DST_SRC else "")


# ═══════════════════════════════════════════════════════════════
# 事务的**声明**（§3.11 的三列，做成数据）
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TxnSpec:
    """事务注册表里的一行 —— 描述"这类事务长什么样"。

    与 `Transaction` 的分工：
      · `TxnSpec` 是**声明**（有哪些事务、各自什么形态），来自
        `schema/txn.registry.json`，是数据；
      · `Transaction` 是**一次实例**（带 mask、带地址、带 tag），由
        `compile/templates.py` 从声明造出来。

    混在一起的话，"事务长什么样"和"这次事务用了哪些核"就分不清了 ——
    而前者是所有 case 共享的、后者是每个 case 独有的。
    """

    id: str
    ops: Tuple[str, ...]
    group: str = ""
    requires: Tuple[str, ...] = ()
    hard: Tuple[HardConstraint, ...] = ()
    effects: Tuple[Effect, ...] = ()
    cfg: str = ""
    #: 角色 → 对象名，由 DSL 的 `alloc[].role` 提供。
    #: 形如 `{"binds": ["wgt", "in"], "writes": ["out"]}`。
    #: 文档 §3.14.4 要求计算类必须带 binds/writes，却没说怎么找对象 —— 靠这个。
    roles: Dict[str, List[str]] = field(default_factory=dict)
    note: str = ""
    #: 文档列了但**编码表里没有**（或标了暂不做）的 —— 生成器不选它。
    #: 留着而不是删掉：文档与编码表的分歧本身就是要让人看见的信息。
    deferred: bool = False

    @property
    def primary_op(self) -> str:
        """事务的"主指令" —— 最后一条（drv 那条）。

        文档里 pre 在前、drv 在后，这个顺序就是发射顺序，不是排版。
        """
        return self.ops[-1] if self.ops else ""

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"id": self.id, "group": self.group,
                               "ops": list(self.ops)}
        if self.requires:
            out["requires"] = list(self.requires)
        if self.hard:
            out["hard"] = [h.to_dict() for h in self.hard]
        if self.effects:
            out["effects"] = [e.to_dict() for e in self.effects]
        if self.cfg:
            out["cfg"] = self.cfg
        if self.note:
            out["note"] = self.note
        return out


class TransactionRegistry:
    """事务声明表。

    构造时**对着 op 注册表校验**：每条事务引用的 op 都得存在。
    这是两个数据源之间唯一的连接点，所以必须在这里拦住 ——
    漏过去的话，生成器会在造事务时才发现"没有这条指令"，
    而那时已经在一个深层调用里了。
    """

    def __init__(self, specs: Sequence[TxnSpec]) -> None:
        self._specs: Dict[str, TxnSpec] = {}
        for spec in specs:
            if spec.id in self._specs:
                raise RegistryError(f"事务 id 重复：{spec.id}", target=spec.id)
            if not spec.ops:
                raise RegistryError(f"事务 {spec.id} 没有任何 op", target=spec.id,
                                    fix="事务至少要有一条指令")
            self._specs[spec.id] = spec
        if not self._specs:
            raise RegistryError("事务注册表是空的")

    def get(self, txn_id: str) -> TxnSpec:
        spec = self._specs.get(txn_id)
        if spec is None:
            raise RegistryError(f"没有事务 {txn_id!r}", target=txn_id,
                                fix=f"已知：{', '.join(self.ids()[:12])}")
        return spec

    def find(self, txn_id: str) -> Optional[TxnSpec]:
        return self._specs.get(txn_id)

    def __contains__(self, txn_id: object) -> bool:
        return txn_id in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def ids(self) -> List[str]:
        return sorted(self._specs)

    def all(self) -> List[TxnSpec]:
        return [self._specs[i] for i in self.ids()]

    def of_group(self, group: str) -> List[TxnSpec]:
        return [s for s in self.all() if s.group == group]

    def available(self) -> List[TxnSpec]:
        """生成器**能选**的那些 —— 排掉已知不可用的。

        `txn_pool.include` 里写了不可用的事务时，由调用方报错；
        这里只负责把"哪些能用"说清楚。
        """
        return [s for s in self.all() if not s.deferred]

    def deferred(self) -> List[TxnSpec]:
        return [s for s in self.all() if s.deferred]

    def groups(self) -> List[str]:
        seen: List[str] = []
        for spec in self.all():
            if spec.group and spec.group not in seen:
                seen.append(spec.group)
        return seen

    def validate_against(self, ops: OpRegistry) -> None:
        """每条事务引用的 op 都要在 op 注册表里存在且能编码。

        **这是两个数据源之间唯一的连接点。** 放在这里而不是使用时判，
        是因为"表里的指令名拼错了"和"生成器写错了"要能分开 ——
        前者是数据缺陷，应当在装载时就报。
        """
        problems: List[str] = []
        for spec in self.all():
            if spec.deferred:
                # 已知不可用的不检查 —— 它引用不到 op 是**预期**的，
                # 理由写在 note 里（见 txn.registry.json）
                continue
            for op_name in spec.ops:
                target = ops.find(op_name)
                if target is None:
                    problems.append(f"{spec.id} 引用了不存在的 op {op_name!r}")
                elif not target.has_encoding:
                    problems.append(
                        f"{spec.id} 引用了没有编码的 op {op_name!r}"
                        f"（非指令 op 不能进事务的指令组）")
        if problems:
            raise RegistryError(
                f"事务注册表与 op 注册表对不上（{len(problems)} 处）："
                + "；".join(problems[:5]),
                target="txn.registry.json",
                fix="检查 schema/txn.registry.json 里的 op 名拼写")
