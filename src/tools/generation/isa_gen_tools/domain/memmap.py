"""memmap —— 地址规则的唯一来源（文档 §3.12.5）。

分配器只回答一个问题：**"这块张量能放在这个地址上吗"**。
答案来自三个集合的交：
    memmap.yaml（全局合法性）∩ DSL.resources（本 case 的可玩池）∩ 事务硬约束
这个模块负责第一项，`compile/resources.py` 做交集。

三件在别处容易被忽略的事，这里显式建模：

1. **`real_size` < `size`**。Common DRAM 声明 512MB，但只有 384MB 是真的，
   最后 128MB 是伪映射 —— **伪空间不得用于生成分配**。
   把 size 当成可分配范围就会把张量放进伪空间，而那在仿真里可能"看起来能跑"。

2. **`reserved` 是显式的区间**。负例要用它做越界，所以它得是**数据**，
   不能只是文档里的一句话。

3. **`lmem` 的两个面**（SPAD / CIMC）共用一块存储，靠 CIMC_flag 区分。
   当成两个独立的 region 处理，地址会重叠 —— 那不是 bug，是同一块内存的两面。

**尺寸是字符串**（`128KB` / `2GB`）—— 人写的配置就该能写人话。
解析放在这里，出错时报的是原始文本而不是一个神秘的数字。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .errors import IsaGenError

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?\s*$", re.I)
_UNITS = {"": 1, "B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3,
          "TB": 1024 ** 4}


def parse_size(text: object) -> int:
    """`"128KB"` → `131072`。认 B/KB/MB/GB/TB，不认就报错。

    不认就报错（而不是"当成字节数"）：`128kb` 写成了 `128` 的话，
    分配器会把 128 字节当成区域大小，然后安静地放不下任何东西。
    """
    if isinstance(text, bool) or isinstance(text, int):
        return int(text)
    match = _SIZE_RE.match(str(text))
    if not match:
        raise IsaGenError(f"看不懂的尺寸 {text!r}；形如 128KB / 2GB")
    value, unit = match.group(1), (match.group(2) or "").upper()
    return int(float(value) * _UNITS[unit])


def format_size(value: int) -> str:
    for unit in ("TB", "GB", "MB", "KB"):
        step = _UNITS[unit]
        if value >= step and value % step == 0:
            return f"{value // step}{unit}"
    return f"{value}B"


@dataclass(frozen=True)
class Region:
    """一块地址区域。

    `per` 说明这块区域是"每核一份"（`lmem`）还是"每 bank 一份"（`dram.common`）
    还是全局共享（`dram.share`）—— 它决定地址里的 `core_id` 字段怎么填。
    """

    name: str
    domain: str
    base: int = 0
    size: int = 0
    per: str = ""
    align: int = 32
    granule: int = 0
    banks: int = 0
    real_size: Optional[int] = None
    comment: str = ""

    @property
    def end(self) -> int:
        """区域末端（不含）。"""
        return self.base + self.size

    @property
    def allocatable_size(self) -> int:
        """**真正能分配的大小** —— 有 `real_size` 时以它为准。

        Common DRAM 声明 512MB 而真实只有 384MB，差的 128MB 是伪映射。
        这条路走错不会报错，只会让张量落进伪空间。
        """
        return int(self.real_size) if self.real_size else self.size

    @property
    def allocatable_end(self) -> int:
        return self.base + self.allocatable_size

    def contains(self, address: int) -> bool:
        """地址在**可分配区**内吗（伪空间不算）。"""
        return self.base <= address < self.allocatable_end

    def contains_span(self, address: int, length: int) -> bool:
        return self.contains(address) and address + length <= self.allocatable_end

    def align_up(self, value: int) -> int:
        step = max(1, self.align)
        return ((value + step - 1) // step) * step

    def to_dict(self) -> Dict[str, object]:
        out: Dict[str, object] = {"name": self.name, "domain": self.domain,
                                  "base": f"0x{self.base:X}",
                                  "size": format_size(self.size),
                                  "align": self.align}
        if self.per:
            out["per"] = self.per
        if self.real_size:
            out["real_size"] = format_size(self.real_size)
        if self.banks:
            out["banks"] = self.banks
        return out


@dataclass(frozen=True)
class MemMap:
    """整份 memmap。

    `regions` 按名字索引；`reserved` 是**闭区间**列表（含两端）——
    文档里写成 `[0x2_1800_0000, 0x2_1FFF_FFFF]` 那种样子就是含两端的。
    """

    version: int = 1
    chips: Dict[str, int] = field(default_factory=dict)
    peers: Tuple[Dict[str, object], ...] = ()
    regions: Tuple[Region, ...] = ()
    reserved: Tuple[Tuple[int, int], ...] = ()
    aliases: Tuple[Dict[str, str], ...] = ()
    source: str = ""

    # ── 查询 ──

    def region(self, name: str) -> Region:
        for item in self.regions:
            if item.name == name:
                return item
        known = ", ".join(sorted(r.name for r in self.regions)) or "（空）"
        raise IsaGenError(f"memmap 里没有区域 {name!r}；已知：{known}")

    def find_region(self, name: str) -> Optional[Region]:
        return next((r for r in self.regions if r.name == name), None)

    def region_names(self) -> List[str]:
        return sorted(r.name for r in self.regions)

    def region_of(self, address: int) -> Optional[Region]:
        """地址落在哪个 region（先匹配到的那个）。

        `lmem` 的两块（SPAD / CIMC）地址是重叠的 —— 谁先匹配取决于声明顺序，
        所以调用方要区分它们是应当**按名字查**（`region("lmem.core.cimc")`），
        不是按地址反查。
        """
        return next((r for r in self.regions if r.contains(address)), None)

    def is_reserved(self, address: int) -> bool:
        return any(low <= address <= high for low, high in self.reserved)

    def overlaps_reserved(self, address: int, length: int) -> bool:
        """这段**跨没跨进**保留区。用于负例的 `reserved_touch` 检查。"""
        if length <= 0:
            return self.is_reserved(address)
        return any(address <= high and low < address + length
                   for low, high in self.reserved)

    def validate_row(self, region: Region, offset: int, length: int) -> None:
        """把"这块放不下"说清楚 —— 分配器只负责喊，不负责猜。"""
        if length > region.allocatable_size:
            raise IsaGenError(
                f"{region.name} 只有 {format_size(region.allocatable_size)}"
                f"（声明 {format_size(region.size)}），装不下 {format_size(length)}")
        if not region.contains_span(region.base + offset, length):
            raise IsaGenError(
                f"{region.name} 里 [{offset:#x}, {offset + length:#x}) 越界；"
                f"可分配范围是 [0, {region.allocatable_size:#x})")

    def to_dict(self) -> Dict[str, object]:
        return {
            "version": self.version,
            "source": self.source,
            "chip": dict(self.chips),
            "regions": [r.to_dict() for r in self.regions],
            "reserved": [f"0x{lo:X}..0x{hi:X}" for lo, hi in self.reserved],
            "peer_count": len(self.peers),
        }
