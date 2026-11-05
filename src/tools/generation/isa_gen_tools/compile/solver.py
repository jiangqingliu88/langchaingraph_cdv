"""约束求解 —— **三层，各自只能干自己的事**（文档 §3.9 / §3.15）。

    L0 硬合法性   编码合法 / 配对 / 对齐 / 地址合法 —— **永不放宽**
    L1 场景约束   精度子集 / 地址子集 / mask 子集 —— 由 DSL 的 resources 定
    L2 意图引导   hazard 密度 / mcast 比例 / fence 频率 —— **只调权重**

分层的意义全在"只调权重"这四个字上
    文档 §3.15 规则 2 明说：覆盖率缺口回灌**只允许落到 L2 意图层旋钮**，
    不允许触碰 L0/L1。所以 L2 在这个模块里的形态是**权重**，不是过滤器 ——
    它能让某类事务更常出现，但**不能**让一条不合法的指令变得合法。

    这也解释了为什么 `intent` 的字段全是比例/密度（见 `domain/dsl.py`）：
    一个能改变"什么是一条合法指令"的旋钮，就不该叫意图旋钮。

L0 在哪里
    大部分 L0 已经在**别处**落实了（这才是对的）：
      · 编码合法性 → op 注册表（没有 encoding 的 op 根本进不了事务）
      · 配对       → `Transaction` 的类型（见 `domain/transaction.py`）
      · 地址合法   → `allocator` + memmap（无解即编译期失败）
    这个模块的 L0 职责是**过滤候选**：已标不可用的事务、没有编码的指令，
    在选池子的时候就被排除 —— 而不是"选中了再检查"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..domain import SolverError, TransactionRegistry, TxnSpec
from ..domain.dsl import DslDocument
from .sequencer import Draw, Sequencer

#: 没写 `cores` 时用的缺省核集合 —— 4 核，与文档例子的 `[0..3]` 一致
DEFAULT_CORES = ("0", "1", "2", "3")


@dataclass(frozen=True)
class TxnChoice:
    """一条事务"这次怎么发" —— 池子选中的是**声明**，这里是**取值**。"""

    spec: TxnSpec
    mask: str
    precision: str = ""
    shape: Tuple[int, ...] = ()
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"txn": self.spec.id, "mask": self.mask}
        if self.precision:
            out["dtype"] = self.precision
        if self.shape:
            out["shape"] = list(self.shape)
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass(frozen=True)
class SolveResult:
    """求解结果。`notes` 记的是**做了但值得说一声**的事（不是错误）。"""

    choices: Tuple[TxnChoice, ...] = ()
    weights: Dict[str, int] = field(default_factory=dict)
    notes: Tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.choices)

    def ids(self) -> List[str]:
        return [c.spec.id for c in self.choices]

    def to_dict(self) -> Dict[str, Any]:
        return {"count": len(self.choices),
                "weights": dict(sorted(self.weights.items())),
                "choices": [c.to_dict() for c in self.choices],
                "notes": list(self.notes)}


# ═══════════════════════════════════════════════════════════════
# L0：候选池（过滤，不是检查）
# ═══════════════════════════════════════════════════════════════

def candidate_specs(dsl: DslDocument, txns: TransactionRegistry) -> List[TxnSpec]:
    """本 case 能选的事务 —— **L0 与 L1 的池子**。

    三条过滤规则，都是"排除"而不是"事后检查"：

    · `txn_pool.include` 写了才用它；没写就是全部可用事务
    · **已标不可用的事务不在池子里**（文档列了但编码表没有的那些）
      —— 选中了才发现"这条编不出来"是一种本该避免的失败
    · **没有 `alloc` 时，要动张量的事务也不在池子里**

    第三条是刻意补的：一份只写了 `meta` 的 DSL（比如 `examples/minimal.yaml`）
    如果还把 `noc_pair_txn` 选进来，它会在需要 `src`/`dst` 角色时报
    `UnresolvedRefError` —— 而使用者压根没打算动任何数据。
    **没有对象可动时，"不搬数据"是唯一说得通的解释**，不是错误。

    `include` 里写了不可用的事务**不是静默忽略**：报 `SolverError` 并说清
    为什么不可用（理由在 `TxnSpec.note` 里）。静默少生成几条事务，
    比报错难查得多。
    """
    available = {spec.id: spec for spec in txns.available()}
    requested = list(dsl.txn_pool.include)

    if not requested:
        specs = list(available.values())
        if not dsl.alloc:
            specs = [s for s in specs if not s.roles]
        return specs

    chosen: List[TxnSpec] = []
    missing: List[str] = []
    for name in requested:
        spec = available.get(name)
        if spec is not None:
            if not dsl.alloc and spec.roles:
                # 点名的这张事务要动张量，而 alloc 是空的 —— 报出来，
                # 别让人对着一条 UnresolvedRefError 去猜"我明明写了 include"
                missing.append(f"{name}（要动张量，但 alloc 是空的）")
                continue
            chosen.append(spec)
            continue
        deferred = txns.find(name)
        if deferred is not None:
            missing.append(f"{name}（文档列了但不可用：{deferred.note[:60]}…）")
        else:
            missing.append(f"{name}（注册表里没有这个事务）")
    if missing:
        raise SolverError(
            f"txn_pool.include 里有 {len(missing)} 条用不了："
            + "；".join(missing[:3]),
            target="txn_pool.include",
            fix=f"可用的事务：{', '.join(sorted(available)[:10])}…")
    return chosen


# ═══════════════════════════════════════════════════════════════
# L1：场景子集（mask / 精度 / 形状）
# ═══════════════════════════════════════════════════════════════

def parse_cores(cores: Sequence[str]) -> List[int]:
    """`["0..3"]` / `["0","1"]` / `[0,1,2]` → 核号列表。

    文档里写成 `[0..3]` 那种区间形式，所以两种都要认。空列表用缺省 4 核。
    """
    if not cores:
        return [int(c) for c in DEFAULT_CORES]
    out: List[int] = []
    for item in cores:
        text = str(item).strip()
        if ".." in text:
            low, _, high = text.partition("..")
            try:
                lo, hi = int(low), int(high)
            except ValueError:
                raise SolverError(f"cores 区间看不懂：{item!r}",
                                  target="resources.cores",
                                  fix="形如 0..3 或直接写核号") from None
            if lo > hi:
                raise SolverError(f"cores 区间反了：{item!r}",
                                  target="resources.cores")
            out.extend(range(lo, hi + 1))
        else:
            try:
                out.append(int(text))
            except ValueError:
                raise SolverError(f"cores 里不是核号：{item!r}",
                                  target="resources.cores",
                                  fix="核号是整数，形如 0..3") from None
    return list(dict.fromkeys(out))


def mask_from_cores(cores: Sequence[int]) -> str:
    """核号列表 → `group_mask` 的十六进制字面量。

    **全零不是合法激励**（文档 §3.11 通用规则 3：mask 全零属非法激励），
    所以空集合报 `SolverError`，不给一个 `0x0` 出去。
    """
    if not cores:
        raise SolverError("mask 是空的 —— 全零 mask 属非法激励",
                          target="resources.cores",
                          fix="至少给一个核")
    value = 0
    for core in cores:
        if core < 0 or core > 63:
            raise SolverError(f"核号 {core} 超出 6b_grp_mask 的表达范围 [0,63]",
                              target="resources.cores", fix="核号 0..63")
        value |= 1 << int(core)
    return f"0x{value:04X}"


def l1_precision(dsl: DslDocument, draw: Draw) -> str:
    """精度 → 从 `precision_mix` 按权重抽。没声明就是空（不定精度）。"""
    if not dsl.precision_mix:
        return ""
    return str(draw.weighted(dsl.precision_mix))


def l1_shape(dsl: DslDocument, draw: Draw) -> Tuple[int, ...]:
    """形状 → 每个维度各自从 `shape_space` 里抽。

    文档字段约定第 3 条：shape_space 是**离散枚举**，"保证每个取值均可映射至
    合法 tile 边界"。所以这里不做取整/截断 —— 取整会把一个不在枚举里的形状
    造出来，那正好破坏那条保证。
    """
    if not dsl.shape_space:
        return ()
    # 维度名排序取定，不靠 dict 的插入序 —— 顺序本身要是输入的一部分
    return tuple(int(draw.choice(dsl.shape_space[key]))
                 for key in sorted(dsl.shape_space))


# ═══════════════════════════════════════════════════════════════
# L2：意图引导（只调权重）
# ═══════════════════════════════════════════════════════════════

def l2_weights(dsl: DslDocument, specs: Sequence[TxnSpec]) -> Dict[str, int]:
    """基础权重 —— `txn_pool.weights` 覆盖，没写就是 1。

    这一层**不做过滤**：权重 0 意味着"这次不抽它"，是意图不是合法性。
    """
    weights = {spec.id: int(dsl.txn_pool.weights.get(spec.id, 1))
               for spec in specs}
    return weights


def l2_bias(dsl: DslDocument, weights: Dict[str, int],
            specs: Sequence[TxnSpec]) -> Tuple[Dict[str, int], List[str]]:
    """按意图调整权重。**只动权重，不碰合法性。**

    三个旋钮各自的作用（都可为 0，此时什么都不做）：

    · `hazard_density` 高 → 提高"会和前序争用资源"的事务权重。
      具体哪类是争用源按事务的效应判（move / compute 会动内存）。
    · `mcast_mix` 高 → 提高带多播的事务权重（`tld_txn` 的效应里写了"支持多播"）。
    · `fence_every_n_epochs` 不在这里 —— 那是**编排**的事（`epochs.py`），
      不是"哪类事务更常出现"。

    返回值第二项是 notes：把"意图没有生效"说出来（比如 `illegal_ratio > 0`
    但文档说负例不进随机空间），而不是假装它生效了。
    """
    notes: List[str] = []
    biased = dict(weights)
    intent = dsl.intent

    if intent.hazard_density > 0:
        shared = _contention_prone(specs)
        boost = 1 + int(round(intent.hazard_density * 3))
        for name in shared:
            biased[name] = max(1, biased.get(name, 1)) * boost
        notes.append(f"hazard_density={intent.hazard_density}："
                     f"{len(shared)} 类争用型事务权重 ×{boost}")

    if intent.mcast_mix:
        mcast = sum(v for k, v in intent.mcast_mix.items() if k != "unicast")
        if mcast > 0:
            targets = [s.id for s in specs if _supports_mcast(s)]
            boost = 1 + int(round(mcast * 3))
            for name in targets:
                biased[name] = max(1, biased.get(name, 1)) * boost
            notes.append(f"mcast 比例 {mcast:.2f}：{len(targets)} 类多播事务"
                         f"权重 ×{boost}")

    if intent.illegal_ratio > 0:
        # 文档 §3.9 明说"负例采用定向方式构建，**不纳入随机空间**"。
        # 所以这里不实现随机负例 —— 但也不能装作没这回事。
        notes.append(
            f"illegal_ratio={intent.illegal_ratio} 未生效："
            "文档 §3.9 规定负例只走定向构建，不进随机空间（M6 的 run_explain 会重复提示）")

    return biased, notes


def _contention_prone(specs: Sequence[TxnSpec]) -> List[str]:
    """会和前序争用资源的事务 —— 按效应判（动内存的那些）。

    判据写在数据里（`effects`），不写在这里的名字表里：新加一条搬移类事务时，
    只要它的效应里有 `move`/`write`，它就自动被算进来。
    """
    prone = []
    for spec in specs:
        kinds = {effect.kind for effect in spec.effects}
        if kinds & {"move", "write", "read", "compute"}:
            prone.append(spec.id)
    return prone


def _supports_mcast(spec: TxnSpec) -> bool:
    return any("多播" in (effect.span or "") or "mcast" in (effect.span or "").lower()
               for effect in spec.effects)


# ═══════════════════════════════════════════════════════════════
# 求解：选事务 + 定取值
# ═══════════════════════════════════════════════════════════════

def solve(dsl: DslDocument, txns: TransactionRegistry, *,
          sequencer: Sequencer, count: int) -> SolveResult:
    """按三层约束选 `count` 条事务，各自定下 mask / 精度 / 形状。

    **顺序是刻意的**：先 L0/L1 缩池子（候选 + 权重），再 L2 调权重，
    最后才按权重抽 —— 反过来的话，L2 的偏置会被 L1 的过滤无声地抹掉一部分。
    """
    if count <= 0:
        return SolveResult()

    specs = candidate_specs(dsl, txns)                    # L0 + L1（池子）
    if not specs:
        raise SolverError("没有任何可用的事务可以生成",
                          target="txn_pool.include",
                          fix="检查 include 与资源声明")

    weights = l2_weights(dsl, specs)
    weights, notes = l2_bias(dsl, weights, specs)

    picker = sequencer.draw("txn:pick")                  # L2 的抽签流
    valuer = sequencer.draw("txn:value")                 # L1 的取值流
    cores = parse_cores(dsl.resources.cores)
    mask = mask_from_cores(cores)

    choices: List[TxnChoice] = []
    for index in range(count):
        spec = _weighted_spec(specs, weights, picker)
        precision = l1_precision(dsl, valuer)
        shape = l1_shape(dsl, valuer)
        choices.append(TxnChoice(spec=spec, mask=mask, precision=precision,
                                 shape=shape, reason=f"#{index + 1}"))

    return SolveResult(choices=tuple(choices), weights=weights, notes=tuple(notes))


def _weighted_spec(specs: Sequence[TxnSpec], weights: Dict[str, int],
                   draw: Draw) -> TxnSpec:
    """按权重抽一条事务。

    权重全零时**退化成均匀**而不是报错 —— 一份把权重都写成 0 的 DSL
    大概是笔误，但因此让整个编译停摆，比"生成了一份均匀的"更糟。
    （均匀也不是静默的：调用方从 `SolveResult.weights` 能看出来。）
    """
    by_id = {spec.id: spec for spec in specs}
    table = {name: float(weights.get(name, 1)) for name in by_id}
    if sum(table.values()) <= 0:
        table = {name: 1.0 for name in by_id}
    return by_id[str(draw.weighted(table))]
