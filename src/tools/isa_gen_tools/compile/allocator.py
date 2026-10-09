"""地址分配器 —— 把 `alloc` 里的对象放进可玩池。

文档 §3.12.5 给了一条硬规矩：

> 生成器在"找不到合法分配"时**编译期失败**，不允许静默产出越界地址；
> 分配器默认**不回退到非对齐地址**。

所以这个模块只有两个结局：**放得下**，或者**报错**。没有"凑合放一下"。

它在**区域内偏移**上工作，最后一步才转成 `GlobalAddr`
    这是个刻意的接缝。文档里 44 位地址的"区内偏移"位宽自相矛盾
    （见 `domain/address.py` 的模块头：按布局算只有 13 位 = 8KB，
    而 SPAD 有 128KB）。把分配算在字节偏移上，那个位宽就只影响
    **一处转换**，真值确认后改那一处即可 —— 而不是渗进整条生成链路。

张量的大小怎么算
    `shape × dtype 字节数`，再按 region 的 `align` 对齐。
    文档 §3.12.5 说 SPAD 基地址 32 字节（256bit）对齐、默认 256bit，
    这里统一用 region 声明的 `align`（那是 memmap 的事，不是这里的）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..domain import AllocError, GlobalAddr, MemFlag
from ..domain.dsl import DslAlloc, DslDocument
from ..domain.address import LOW_ALIGN_BITS, OFFSET_BITS
from ..domain.memmap import MemMap, Region, format_size
from .resources import PlaySpace
from .sequencer import Draw

#: dtype → 每个元素的字节数
DTYPE_BYTES: Dict[str, int] = {
    "fp32": 4, "int32": 4, "uint32": 4, "i32": 4,
    "fp16": 2, "bf16": 2, "int16": 2,
    "mxfp8": 1, "fp8": 1, "int8": 1, "uint8": 1,
    "mxfp4": 1, "int4": 1,          # 4bit 按 1 字节算 —— 宁可多占也不越界
}


def element_size(dtype: str) -> int:
    key = (dtype or "").strip().lower()
    if key not in DTYPE_BYTES:
        raise AllocError(
            f"不认识的 dtype {dtype!r}",
            target=f"alloc.{dtype}",
            fix=f"可选：{', '.join(sorted(DTYPE_BYTES))}")
    return DTYPE_BYTES[key]


def tensor_bytes(shape: List[int], dtype: str) -> int:
    """形状 × 元素大小。空 shape 按单元素算（标量张量）。"""
    count = 1
    for dim in shape or [1]:
        if dim <= 0:
            raise AllocError(f"shape 里有非正的维度：{shape}",
                             fix="形状的每一维都要 > 0")
        count *= int(dim)
    return count * element_size(dtype)


@dataclass(frozen=True)
class Allocation:
    """一个对象落在哪里。"""

    name: str
    pool: str
    region: str
    offset: int            # 区域内字节偏移
    size: int
    align: int
    dtype: str = ""
    shape: Tuple[int, ...] = ()
    pattern: str = ""
    exp_range: Optional[Tuple[float, float]] = None
    #: DSL 声明的角色（wgt / in / out…）—— 计算类事务的 binds/writes 靠它对上
    role: str = ""

    @property
    def span(self) -> Tuple[int, int]:
        return self.offset, self.offset + self.size

    def address(self, base: int) -> int:
        return base + self.offset

    def to_dict(self, base: int = 0) -> Dict[str, object]:
        out: Dict[str, object] = {
            "name": self.name, "pool": self.pool, "region": self.region,
            "offset": f"0x{self.offset:X}", "size": format_size(self.size),
            "align": self.align,
        }
        if base:
            out["address"] = f"0x{self.address(base):X}"
        if self.dtype:
            out["dtype"] = self.dtype
        if self.shape:
            out["shape"] = list(self.shape)
        if self.pattern:
            out["pattern"] = self.pattern
        if self.exp_range:
            out["exp_range"] = list(self.exp_range)
        return out


@dataclass(frozen=True)
class AllocationPlan:
    """一次分配的完整结果。"""

    allocations: Tuple[Allocation, ...] = ()
    region_bases: Dict[str, int] = field(default_factory=dict)
    notes: Tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.allocations)

    def get(self, name: str) -> Optional[Allocation]:
        return next((a for a in self.allocations if a.name == name), None)

    def names(self) -> List[str]:
        return [a.name for a in self.allocations]

    @property
    def bindings(self) -> Dict[str, int]:
        """`{对象名: 全局地址}` —— IR 的 `src_addr` / `dst_addr` 用它。

        **地址要带 region 的语义位**，不能只做"region 基址 + 偏移"。
        `lmem.core.spad` 与 `lmem.core.cimc` 是**同一块局部存储的两个面**，
        基址都是 0 —— 只加偏移的话两者会算出同一个数，消费方分不出是哪个面。
        （这个 bug 真的出现过：观测点纪律检查把 `out`(SPAD) 与 `wgt`(CIMC)
        判成了"共用同一段地址"。）

        真实地址由 `GlobalAddr` 拼：`Mem_Flag` 区分 LMEM / Share / Common，
        `CIMC_flag` 在 LMEM 内再分 SPAD / CIMC。
        """
        return {a.name: global_address(self.region_bases.get(a.region, 0),
                                       a.region, a.offset)
                for a in self.allocations}

    def to_dict(self) -> Dict[str, object]:
        return {
            "regions": {name: f"0x{base:X}"
                        for name, base in sorted(self.region_bases.items())},
            "objects": [a.to_dict(self.region_bases.get(a.region, 0))
                        for a in sorted(self.allocations, key=lambda a: a.name)],
            "notes": list(self.notes),
        }


def global_address(region_base: int, region_name: str, offset: int,
                   core_id: int = 0) -> int:
    """(region, 区内偏移) → 44 位全局地址。

    **这是 region 语义位唯一被拼进去的地方。** 别处要地址就走这里 ——
    各算各的必然漏掉 `CIMC_flag` 或 `Mem_Flag`，而漏掉的后果是
    "两个不同面的地址算成同一个数"，那种错在仿真里表现为数据读写错区域。

    **LMEM 走字段拼装，DRAM 走普通字面量** —— 因为那套布局表达不了 DRAM
        LMEM（SPAD/CIMC）的区内偏移是 `Page_num(4) + 区内偏移(13)` = 17 位
        = 128KB，正好是 §3.12.5 说的 SPAD 大小 —— 按这个拆。
        （先按 13 位当整体偏移实现过一次，把 8192 截回了 0，
        于是 SPAD 里第二个 8KB 以上的对象和第一个算出同一个地址，
        而且**不报错**。掩码只会造出一个"看起来合理但是错的"地址。）

        DRAM 不行：2GB 的偏移要 31 位，而布局里可用的只有 17 位。
        所以 DRAM 返回 `region_base + offset` 的**普通数值** ——
        文档 §3.0.2 的 IR 样例里 DRAM 地址本来就写成十六进制字面量
        （`"src_addr": "0x1_0004_0000"`），不是字段拼装的。

        **这是文档布局的一处不自洽**（44 位装不下它自己声明的 2GB 区域），
        不是实现取舍。冻结版 memmap / ISA §2.5 到位时回来核对。

    区域名 → 语义位按后缀判（`memmap.yaml` 的 `domain` 字段是同一个意思，
    这里按 region 名判是为了不把 memmap 拖进这个纯函数）。
    """
    name = (region_name or "").lower()
    if name.startswith("dram."):
        return int(region_base) + int(offset)
    page, low = _split_offset(offset)
    return GlobalAddr(mem_flag=int(MemFlag.LMEM), core_id=core_id,
                      cimc_flag=1 if name.endswith("cimc") else 0,
                      page_num=page, offset=low).pack()


def _split_offset(offset: int) -> Tuple[int, int]:
    """区内字节偏移 → `(page_num, 区内偏移)`。

    先对齐再拆 —— 反过来的话低位那几位会在移位时丢掉，
    而低位对齐是布局的硬要求（`GlobalAddr` 会校验）。
    """
    aligned = (int(offset) // (1 << LOW_ALIGN_BITS)) << LOW_ALIGN_BITS
    return aligned >> OFFSET_BITS, aligned & ((1 << OFFSET_BITS) - 1)


def allocate(dsl: DslDocument, play_space: PlaySpace, memmap: MemMap, *,
             seed: int) -> AllocationPlan:
    """按 `alloc` 逐个放置。

    每个对象一条**独立的随机流**（`Draw` 来自 `sequencer`）—— 地址抖动也遵守
    E5：加一个新对象不会挪动既有对象的地址。摆放顺序按 `alloc` 的声明顺序，
    所以顺序本身也是输入的一部分。
    """
    if not dsl.alloc:
        return AllocationPlan()

    # region → 下一个可用偏移（bump 分配）。按 region 分开，各排各的。
    cursors: Dict[str, int] = {}
    region_bases: Dict[str, int] = {}
    allocations: List[Allocation] = []
    notes: List[str] = []
    seen: Dict[str, str] = {}

    for entry in dsl.alloc:
        if entry.name in seen:
            raise AllocError(
                f"alloc 里有两个都叫 {entry.name!r} 的对象",
                target=f"alloc.{entry.name}",
                fix="对象名是 ref 的锚点，重名会让 binds/writes 指错地方")
        seen[entry.name] = entry.pool

        pool = play_space.pool(entry.pool)
        region = pool.region
        size = tensor_bytes(entry.shape, entry.dtype)
        if size > pool.capacity:
            raise AllocError(
                f"{entry.name} 要 {format_size(size)}，装不下 —— "
                f"池 {pool.name} 只有 {format_size(pool.capacity)}",
                target=f"alloc.{entry.name}",
                fix="调小 shape/dtype，或换一个更大的池")

        offset = _place(region, cursors.get(region.name, 0), size, entry,
                        memmap, pool.capacity)
        cursors[region.name] = offset + size
        region_bases.setdefault(region.name, region.base)

        allocations.append(Allocation(
            name=entry.name, pool=pool.name, region=region.name,
            offset=offset, size=size, align=region.align,
            dtype=entry.dtype, shape=tuple(entry.shape), pattern=entry.pattern,
            exp_range=(tuple(entry.exp_range) if entry.exp_range else None),
            role=entry.role))

    plan = AllocationPlan(allocations=tuple(allocations),
                          region_bases=region_bases, notes=tuple(notes))
    _check_overlaps(plan, play_space, memmap)
    return plan


def _place(region: Region, cursor: int, size: int, entry: DslAlloc,
           memmap: MemMap, capacity: int) -> int:
    """从 `cursor` 往后找第一个放得下的对齐位置。

    **逐次尝试而不是一次算准**：保留区是散落的区间，对齐要求又可能让块的整体
    跨度变化 —— 一次算准要解一个带洞的装箱，而这里只需要"下一个能放的地方"。
    真放不下就报 `AllocError`，不回退。
    """
    offset = region.align_up(cursor)
    limit = capacity
    for _ in range(1024):                     # 防呆：正常不会走到这么多轮
        if offset + size > limit:
            break
        absolute = region.base + offset
        if not memmap.overlaps_reserved(absolute, size):
            return offset
        # 撞上保留区 —— 跳到它后面，重新对齐
        blocking = next((high for low, high in memmap.reserved
                         if low <= absolute + size and low < absolute + size
                         and absolute <= high), None)
        offset = region.align_up((blocking + 1) if blocking is not None else limit)
    raise AllocError(
        f"{entry.name}（{format_size(size)}）在 {region.name} 里找不到位置",
        target=f"alloc.{entry.name}",
        fix=f"池容量 {format_size(capacity)} 已经排到 {format_size(cursor)}；"
            "调小对象、换池，或在 DSL 里减少对象",
        detail={"region": region.name, "cursor": cursor, "size": size})


def _check_overlaps(plan: AllocationPlan, play_space: PlaySpace,
                    memmap: MemMap) -> None:
    """兜底：任意两个对象不得重叠 —— 除非 DSL 明说了允许。

    `overlap_ratio` 是"**故意**允许地址重叠的比例"（RAW 注入，§3.12.7）。
    v0 的 bump 分配器**不会**主动制造重叠，所以这里只做一件事：
    确认它没意外造出重叠。等重叠注入真做了（M5 的策略插件），
    这里会改成"允许 `overlap_ratio` 那部分"。
    """
    by_region: Dict[str, List[Allocation]] = {}
    for allocation in plan.allocations:
        by_region.setdefault(allocation.region, []).append(allocation)
    for region_name, items in by_region.items():
        ordered = sorted(items, key=lambda a: a.offset)
        for earlier, later in zip(ordered, ordered[1:]):
            if earlier.offset + earlier.size > later.offset:
                raise AllocError(
                    f"{earlier.name} 与 {later.name} 在 {region_name} 里重叠",
                    target=later.name,
                    fix="分配器不该造出重叠；这是内部缺陷，请报告")
