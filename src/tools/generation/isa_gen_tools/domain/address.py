"""44 位全局地址 —— 文档 §3.12.2 的字段布局。

    global_addr[43:0] = { Die_ID[43:42], Cluster_ID[41:40], Mcast_mode[39:36],
                          Mem_Flag[35:33], 保留[32:22], Core_ID[21:18],
                          CIMC_flag[17], Page_num[16:13], 区内偏移 }

两个刻意的设计

1. **保留位显式建模**（`[32:22]` 那 11 位）。
   不把它悄悄跳过是有原因的：一段 11 位的空洞意味着"地址位不连续"，
   任何按位拼接的代码都得知道它在那儿，否则 `Mem_Flag` 会挪到 `Core_ID`
   上面去 —— 而那种错**不会报错**，只会让地址指向别处。

2. **只有 44 位一种**。文档 §3.12.4 明说"36→38→40→44 并存是禁止的"。
   所以这里没有"版本"参数：多一个版本就多一条会走错的路。

关于"区内偏移"的位宽 —— **文档在这里自相矛盾，这里不猜**
    把布局里点名的字段减掉（44 − 2 − 2 − 4 − 3 − 11 − 4 − 1 − 4），
    "区内偏移"只剩 **13 位 = 8KB**。

    而同一份文档的 §3.12.5 说：`lmem.core.spad` 是 **128KB**、
    `dram.share` 是 **2GB**。一个 13 位的区内偏移**装不下任何一个**。

    所以至少有一处是错的，而且可能是这两种：

      (a) 布局漏写了一个字段（`Page_num[16:13]` 会不会本来就是偏移的高位？
          4 + 13 = 17 位 = 128KB，正好等于 SPAD —— 这个巧合很可疑）
      (b) §3.12.5 的区域尺寸不是按"一个连续区"理解的

    **不替它选。** 这里按字面实现（13 位），并且：
      · `test_address.py::test_offset_width_conflicts_with_region_sizes`
        把这个矛盾**钉成一条测试** —— 冻结版 memmap 到位时，那条测试是活路标；
      · 分配器（`compile/allocator.py`）**在区域内的字节偏移上工作**，
        只在最后一步转成 `GlobalAddr`。换句话说这个位宽只影响一个转换点，
        真值确认后改那一处即可，不会渗进整个生成链路。

    真值以冻结版 `verification/memmap.yaml`(v1.0) 为准 —— 那份文件目前不在仓库里。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Dict, Optional

from .errors import IsaGenError

#: 字段 → 位宽。加总必须 ≤ 44。
FIELD_BITS: Dict[str, int] = {
    "die_id": 2,
    "cluster_id": 2,
    "mcast_mode": 4,
    "mem_flag": 3,
    "reserved": 11,
    "core_id": 4,
    "cimc_flag": 1,
    "page_num": 4,
}

ADDR_BITS = 44
#: 区内偏移占剩下的位 —— 见模块头"关于位宽的没写全的地方"
OFFSET_BITS = ADDR_BITS - sum(FIELD_BITS.values())        # 13
RESERVED_OFFSET = 22                                       # 保留区低位在 22
LOW_ALIGN_BITS = 5                                         # 低 5 位恒 0（32 字节对齐）

#: 各字段的 (低位, 位宽)，由布局表推得 —— 只在这里算一次
FIELD_SHIFTS: Dict[str, tuple] = {}
_shift = 0
for _name in ("offset", "page_num", "cimc_flag", "core_id", "reserved",
              "mem_flag", "mcast_mode", "cluster_id", "die_id"):
    _width = OFFSET_BITS if _name == "offset" else FIELD_BITS[_name]
    FIELD_SHIFTS[_name] = (_shift, _width)
    _shift += _width

assert _shift == ADDR_BITS, f"字段位宽加总 {_shift} ≠ {ADDR_BITS}"


class MemFlag(IntEnum):
    """地址落在哪一块存储（文档 §3.12.2）。

    多播模式**不在这里** —— 文档 §3.12.4 第 4 条明说 mcast 是独立的意图参数，
    不是地址位。这里是另一个同名的 4 位字段（`mcast_mode`），两者别混。
    """

    LMEM = 0
    SHARE_DRAM = 1
    COMMON_DRAM = 2


class McastMode(IntEnum):
    """地址里的多播字段。**与 DSL 的 intent.mcast_mix 不是一回事**。"""

    UNICAST = 0
    MCAST4 = 1
    MCAST8 = 2
    BCAST = 3


@dataclass(frozen=True)
class GlobalAddr:
    """一条 44 位全局地址。frozen —— 地址是值，不是可以就地改的东西。

    缺省全零（`LMEM` / 单播 / 核 0 / 偏移 0），也就是"这个核的 SPAD 开头"。
    """

    die_id: int = 0
    cluster_id: int = 0
    mcast_mode: int = int(McastMode.UNICAST)
    mem_flag: int = int(MemFlag.LMEM)
    core_id: int = 0
    cimc_flag: int = 0
    page_num: int = 0
    offset: int = 0

    def __post_init__(self) -> None:
        for name, width in (("die_id", FIELD_BITS["die_id"]),
                            ("cluster_id", FIELD_BITS["cluster_id"]),
                            ("mcast_mode", FIELD_BITS["mcast_mode"]),
                            ("mem_flag", FIELD_BITS["mem_flag"]),
                            ("core_id", FIELD_BITS["core_id"]),
                            ("cimc_flag", FIELD_BITS["cimc_flag"]),
                            ("page_num", FIELD_BITS["page_num"]),
                            ("offset", OFFSET_BITS)):
            value = int(getattr(self, name))
            if value < 0 or value >= (1 << width):
                raise IsaGenError(
                    f"{name}={value} 超出 {width} 位字段的范围 [0, {(1 << width) - 1}]"
                    f"（{type(self).__name__}）")
        if self.offset % (1 << LOW_ALIGN_BITS):
            raise IsaGenError(
                f"offset={self.offset} 未按 {1 << LOW_ALIGN_BITS} 字节对齐"
                f"（布局的低 {LOW_ALIGN_BITS} 位恒 0）")

    # ── 编解码 ──

    def pack(self) -> int:
        """→ 44 位整数。"""
        value = 0
        for name, (shift, width) in FIELD_SHIFTS.items():
            if name == "reserved":
                continue                       # 保留位恒 0，但位宽照样占着
            value |= (int(getattr(self, name)) & ((1 << width) - 1)) << shift
        return value

    def to_hex(self) -> str:
        return f"0x{self.pack():011X}"

    @classmethod
    def unpack(cls, value: int) -> "GlobalAddr":
        if value < 0 or value >= (1 << ADDR_BITS):
            raise IsaGenError(f"{value:#x} 超出 {ADDR_BITS} 位地址范围")
        kwargs = {}
        for name, (shift, width) in FIELD_SHIFTS.items():
            if name == "reserved":
                continue
            kwargs[name] = (value >> shift) & ((1 << width) - 1)
        return cls(**kwargs)

    @property
    def reserved_bits(self) -> int:
        """保留区那 11 位 —— 单独取出来，免得有人以为它们"不存在"。"""
        shift, width = FIELD_SHIFTS["reserved"]
        return (self.pack() >> shift) & ((1 << width) - 1)

    # ── 派生 ──

    @property
    def mem_flag_enum(self) -> MemFlag:
        return MemFlag(self.mem_flag)

    @property
    def region_key(self) -> str:
        """落在哪个 region 域 —— 与 memmap 的 `domain` 字段同名。

        LMEM 再按 CIMC_flag 分 SPAD / CIMC：它们是同一块局部存储的两个面。
        """
        if self.mem_flag == int(MemFlag.LMEM):
            return "lmem.cimc" if self.cimc_flag else "lmem.spad"
        if self.mem_flag == int(MemFlag.SHARE_DRAM):
            return "dram.share"
        return "dram.common"

    def with_offset(self, offset: int) -> "GlobalAddr":
        return replace(self, offset=int(offset))

    def shifted(self, delta: int) -> "GlobalAddr":
        """偏移整体挪一段 —— 分配器排布张量时用。"""
        return replace(self, offset=self.offset + int(delta))

    def describe(self) -> str:
        return (f"die{self.die_id}/clu{self.cluster_id}/core{self.core_id}"
                f"/{self.region_key}+{self.offset:#x}")


# ═══════════════════════════════════════════════════════════════
# T4 为什么**不在这里**实现
# ═══════════════════════════════════════════════════════════════
#
# 文档 §3.12.3 给的三个 T4 公式全是**反向**的 —— 从 rs1val/rs2val 的位推出
# 基址，形如：
#
#     base_addr_lmem[37:0] = { rs1val[21:18], 12'd0, rs1val[17:1], 5'd0 }
#
# 生成器需要的是正向（地址 → 该往 rs1val 填什么位段），而反向公式推不出唯一的
# 正向映射（位段之间有 12 位空洞，空洞里的信息在反向式里根本不存在）。
#
# 而且 v0 **用不到它**：IR 里的 `src_addr` / `dst_addr` 是全局地址的十六进制
# 字面量（见文档 §3.0.2 的 IR 样例 `"src_addr": "0x1_0004_0000"`），
# 那是 T3 的产物。T4 是**编码器那一步**的事。
#
# 所以这里只留一句说明，不留一个猜出来的实现 —— 猜出来的位段拼装**不会报错**，
# 只会把地址指向别处，然后在仿真里表现为"数据搬错了地方"。等编码器（v1）
# 落地时按冻结版规格补，同时补往返测试。

