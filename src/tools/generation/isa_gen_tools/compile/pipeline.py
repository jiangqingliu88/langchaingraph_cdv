"""编译流水线 —— **唯一**把各个阶段按序串起来的地方（文档 §3.5 的六步）。

    DSL ─schema─► 资源 ─alloc─► 地址 ─solve─► 事务 ─epoch─► 时间窗 ─► IR

为什么必须只有一个编排者
    每一段单独都能跑，但"顺序"本身是有语义的：地址必须先分配好，
    事务才能取到 `src_addr`；事务必须先选好，才能算涨 hazard 的权重。
    散在多处调用会让"这次的产出是哪几步跑出来的"变得没法回答 ——
    而这个工具的全部卖点是**可复现**。

`CompileReport` 是给"这次到底发生了什么"用的
    它记的不只是产物，还有：用了哪个 seed、派生了几条流、L2 的意图生效了几项、
    有哪些 note。**notes 不是错误**，是"做了但值得说一声"的事
    （比如 `illegal_ratio > 0` 但文档规定负例不进随机空间）。
    少了它，使用者只能从产物反推过程 —— 那正是这个工具想消灭的东西。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..domain import (IrProgram, OpRegistry, Transaction, TransactionRegistry,
                      TxnSpec, UnresolvedRefError)
from ..domain.dsl import DslDocument
from ..domain.memmap import MemMap
# 直接从子模块 import 名字，**不要**走 `from . import x as x_mod` ——
# `compile/__init__.py` 也导出了同名的函数（`annotate` / `solve`…），
# 于是 `from . import annotate` 拿到的是**函数**而不是模块，
# 报出一句 `'function' object has no attribute 'annotate'` 这种自相矛盾的错。
from .allocator import AllocationPlan, allocate
from .annotate import annotate, check_observation_discipline
from .epochs import (EPOCH_FENCE_TXN, EPOCH_SYNC_TXN, Schedule, plan_epochs)
from .solver import solve
from .templates import instantiate, ref_set
from .resources import PlaySpace, build_play_space
from .sequencer import Draw, Sequencer

#: 没写 `txn_pool` 也没给 `max_txns` 时默认生成多少条 —— 够看出结构，不至于刷屏
DEFAULT_TXN_COUNT = 24


@dataclass(frozen=True)
class CompileReport:
    """一次编译的**过程记录** —— 与产物一起给出去。"""

    seed: int = 0
    name: str = ""
    txn_count: int = 0
    instruction_count: int = 0
    epoch_count: int = 0
    streams: Tuple[str, ...] = ()            # 派生过哪些随机流（可复现链）
    play_space: Dict[str, Any] = field(default_factory=dict)
    allocations: Dict[str, Any] = field(default_factory=dict)
    weights: Dict[str, int] = field(default_factory=dict)
    notes: Tuple[str, ...] = ()
    elapsed_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seed": self.seed, "name": self.name,
            "txn_count": self.txn_count,
            "instruction_count": self.instruction_count,
            "epoch_count": self.epoch_count,
            "streams": list(self.streams),
            "play_space": self.play_space,
            "allocations": self.allocations,
            "weights": self.weights,
            "notes": list(self.notes),
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True)
class CompileOutput:
    """一次编译的全部产物（对应文档 §3.6 的落盘布局）。"""

    program: IrProgram
    report: CompileReport
    case: Dict[str, Any] = field(default_factory=dict)
    preload: Dict[str, Any] = field(default_factory=dict)
    expect: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case": self.case,
            "report": self.report.to_dict(),
            "ir": self.program.to_dict(),
            "preload": self.preload,
            "expect": self.expect,
        }


def compile_dsl(dsl: DslDocument, *, txns: TransactionRegistry, ops: "OpRegistry",
                memmap: MemMap, seed: Optional[int] = None,
                max_txns: Optional[int] = None, clock=None) -> CompileOutput:
    """跑完六个阶段，返回全部产物。

    **两张表都要**，它们管的事不同：
      · `txns`（事务表）挑"生成哪些事务"
      · `ops`（指令表）填"每条指令的字段" —— flags 从那里来，不许手填

    早先把参数只叫 `ops` 却传的事务表，于是模板拿事务表去查指令名，
    报了一句误导性很强的"没有事务 noc_drv_dst_xn"。命名要贴着职责走。

    每一步失败都是**具名 `CompileError`**（见 `domain/errors.py`），
    调用方（`api.run_compile`）把它翻成 `{"error", "kind", "target", "fix"}`。
    """
    started = time.perf_counter()
    # `seed=` 是**覆盖**（CLI 的 `--seed` 就是这个意思），
    # 没给才用 `meta.seed`，再没有才取时间戳。
    resolved_seed = int(seed) if seed is not None else dsl.seed_or(_timestamp(clock))
    sequencer = Sequencer(resolved_seed)
    case = dsl.with_seed(resolved_seed)          # seed 回填（文档字段约定第 1 条）

    # ① 可玩池 —— memmap ∩ DSL.resources
    space = build_play_space(dsl, memmap)

    # ② 地址分配 —— 无解即编译期失败，不回退
    plan = allocate(dsl, space, memmap, seed=resolved_seed)

    # ③ 求解：L0/L1 缩池子 → L2 调权重 → 抽签定取值
    count = int(max_txns if max_txns is not None else DEFAULT_TXN_COUNT)
    solved = solve(dsl, txns, sequencer=sequencer, count=count)
    solved_masks = solved.choices[0].mask if solved.choices else ""

    # ④ 实例化 —— 事务的指令组一起造出来（配对由类型保证）
    value_draw = sequencer.draw("txn:build")
    transactions = [
        instantiate(choice.spec, registry=ops, mask=choice.mask,
                    plan=plan, draw=value_draw)
        for choice in solved.choices
    ]

    # ⑤ 编排：切时间窗 + 插同步点
    schedule = plan_epochs(dsl, transactions, registry=txns,
                           sequencer=sequencer)
    ordered = list(transactions)
    for index in sorted(set(schedule.sync_points) | set(schedule.fence_points)):
        ordered = _insert_sync(ordered, schedule, index, txns, ops, plan,
                               sequencer, mask=solved_masks)

    # tag 统一在这里编 —— 标注要用它做锚点，所以必须在标注**之前**
    ordered = _tag(ordered)

    # ⑥ 标注：补 wait_done / expect_rd，核对 ref 与观测点纪律
    refs = ref_set(plan)
    annotated = annotate(ordered, registry=ops, refs=refs)
    discipline = check_observation_discipline(ordered, plan=plan)

    program = IrProgram.from_transactions(
        annotated.transactions, seed=resolved_seed, name=case.meta.name,
        isa_rev=case.meta.isa_rev, target=case.meta.target,
        memmap_version=f"v{memmap.version}",
        meta={"source": memmap.source})

    elapsed = int((time.perf_counter() - started) * 1000)
    report = CompileReport(
        seed=resolved_seed, name=case.meta.name,
        txn_count=len(annotated.transactions),
        instruction_count=len(annotated.instructions),
        epoch_count=len(schedule), streams=tuple(sequencer.issued),
        play_space=space.to_dict(), allocations=plan.to_dict(),
        weights=solved.weights,
        notes=tuple(_collect_notes(solved, schedule, annotated, discipline)),
        elapsed_ms=elapsed)

    return CompileOutput(
        program=program, report=report,
        case=case.to_dict(),
        preload=_preload(plan),
        expect=_expect(annotated, plan))


# ═══════════════════════════════════════════════════════════════
# 内部
# ═══════════════════════════════════════════════════════════════

def _timestamp(clock) -> int:
    """`meta.seed` 缺省时的时间戳。

    `clock` 可注入 —— 测试与"要可复现的调用方"都不该被墙钟影响。
    这也让这条路径**不是隐藏的随机源**：它是显式传入的。
    """
    if clock is not None:
        return int(clock)
    return int(time.time())


def _insert_sync(ordered: List[Transaction], schedule, index: int,
                 txns: TransactionRegistry, ops: "OpRegistry",
                 plan: AllocationPlan, sequencer: Sequencer,
                 mask: str = "") -> List[Transaction]:
    """在 `index` 个 epoch **之后**插同步点。

    切分点是按事务数算的，所以这里要把它换算成"平铺之后的第几条"。
    """
    into = sum(len(e.transactions) for e in schedule.epochs[:index + 1])
    sync_id = (EPOCH_FENCE_TXN if index in schedule.fence_points
               else EPOCH_SYNC_TXN)
    spec = txns.find(sync_id)
    if spec is None:
        # 编排点名要插的同步事务不在注册表里 —— 报错而不是跳过：
        # 少一个同步点会让时间窗的语义整个变掉，而那只在仿真里表现为"偶尔对不上"
        from ..domain import SolverError
        raise SolverError(f"编排要插 {sync_id}，但事务注册表里没有",
                          target="orchestration.epoch_boundary_sync")
    # **mask 要跟着传** —— 同步指令同样作用在选中的核上。
    # 早先漏了这一个参数，生成出来的 sync/noc_fence 的 mask 是空的，
    # 而在 IR 里"没有 mask"和"mask 全零"看起来一样 —— 后者是非法激励。
    sync = instantiate(spec, registry=ops, plan=plan, mask=mask,
                       draw=sequencer.draw(f"sync:{index}"))
    return ordered[:into] + [sync] + ordered[into:]


def _tag(transactions: Sequence[Transaction]) -> List[Transaction]:
    """编 tag —— `L<n>`，与文档样例的写法一致。

    用序号而不是名字：tag 是 IR 上的锚点（`wait_done` / `expect_rd` 靠它引用），
    它必须**稳定且唯一**。名字会重复（同一类事务出现多次），序号不会。
    """
    return [t.with_tag(f"L{index + 1}") for index, t in enumerate(transactions)]


def _collect_notes(solved, schedule, annotated, discipline) -> List[str]:
    """把各阶段的 note 汇总 —— 顺序固定（阶段顺序），结果才能 diff。"""
    notes: List[str] = []
    notes.extend(solved.notes)
    notes.extend(schedule.notes)
    notes.extend(annotated.notes)
    notes.extend(discipline)
    return notes


def _preload(plan: AllocationPlan) -> Dict[str, Any]:
    """`preload.json` —— setup 阶段的后门清单（文档 §3.6）。

    本工具**不产张量数据**（那是 tensor_gen 的活），只留 `ref` 句柄与
    装载位置。`exp_range` 一起带过去 —— 它是指数安全域（E1），
    tensor_gen 要靠它约束浮点张量的指数。
    """
    return {
        "$comment": "本工具只产出句柄；张量数据由 tensor_gen 按这些句柄生成",
        "entries": [
            {"name": a.name, "ref": f"$t.{a.name}", "region": a.region,
             "offset": f"0x{a.offset:X}", "size": a.size,
             "dtype": a.dtype, "shape": list(a.shape),
             **({"pattern": a.pattern} if a.pattern else {}),
             **({"exp_range": list(a.exp_range)} if a.exp_range else {}),
             **({"role": a.role} if a.role else {})}
            for a in sorted(plan.allocations, key=lambda a: a.name)
        ],
    }


def _expect(annotated, plan: AllocationPlan) -> Dict[str, Any]:
    """`expect.json` —— 比对锚点（文档 §3.6）。

    文档说这份"ISS 就绪后由其覆盖"。在那之前，这里给出的是**工具能自己决定的
    那部分**：观测点落在哪个 tag 上。期望值本身（浮点结果、rdval 的数值）
    要 ISS 才算得出来 —— 工具不猜。
    """
    return {
        "$comment": "锚点由本工具给；期望值待 ISS 覆盖（文档 §3.6）",
        "anchors": [{"tag": tag, "kind": "readback"} for tag in annotated.observations],
        "objects": {a.name: {"region": a.region, "offset": f"0x{a.offset:X}",
                             "dtype": a.dtype, "shape": list(a.shape)}
                    for a in sorted(plan.allocations, key=lambda a: a.name)},
    }
