"""NICE / VNICE 指令字 —— 32bit 的位级打包与解包。

这一层存在的理由
    `domain/opcode.py` 回答「哪条指令的 funct7 / flags 是什么」，
    不回答「这几位在指令字的哪几个 bit 上」。位布局属于**接口约定**
    （芯来 core 的 NICE / VNICE 接口），不是编码表能表达的东西 ——
    两者必须分开存，否则"改一条指令"和"改一次位布局"会混进同一个 diff。

    `funct7` 的解析**不在这里**（`domain/opcode.py:parse_funct7` 已经有了）。
    这里只收**已解析好的整数**，只负责位摆放。

接口（Nuclei NICE / VNICE）
    NICE  = 标量寄存器 32bit，走 RISC-V **custom-0** 空间
    VNICE = 矢量寄存器 128bit，走 RISC-V **custom-1** 空间

    两条的字格式相同，只有 opcode 不同：

        31      25 24   20 19   15 14 13 12 11    7 6      0
        [funct7  ][ rs2  ][ rs1  ][xd][xs1][xs2][ rd   ][opcode]
           7         5        5     1   1   1     5        7
                                       = 32 bit

    `xd/xs1/xs2` 是「本指令用不用 rs1 / rs2 / rd」的使能位 —— 置位才去
    寄存器分配器取号（见 `regalloc.py`）。

为什么 opcode 要从 registry 的**截断字符串**还原
    编码表里 nice 行存 `"1011"`、vnice 行存 `"101011"` —— 这是省掉前导零的
    数字写法，不是 4bit / 6bit 字段。十进制一对就清楚：

        "1011"   = 11 = 0x0B = 0001011 = RISC-V custom-0   → nice
        "101011" = 43 = 0x2B = 0101011 = RISC-V custom-1   → vnice

    正确做法是**按二进制整数解析**（`int(s, 2)`）—— 它对任意位宽都成立。
    "补零到 7 位"在眼下这两个值上碰巧也对，但那是巧合，不是规则。
"""
from __future__ import annotations

from typing import Dict, Optional

#: RISC-V 保留的 4 个 custom opcode。本 ISA 只用了前两个。
CUSTOM_0 = 0b0001011
CUSTOM_1 = 0b0101011
CUSTOM_2 = 0b1011011
CUSTOM_3 = 0b1111011

#: `isa_family` → opcode。这是**接口事实**（芯来 NICE=标量走 custom-0、
#: VNICE=矢量走 custom-1），不是从编码表推的 —— 表里存的是截断值。
FAMILY_OPCODE: Dict[str, int] = {
    "nice": CUSTOM_0,
    "vnice": CUSTOM_1,
}

#: 位域表（低位 → 高位）。`pack` 与 `unpack` 共用这一份，不各写一遍 ——
#: 分开写的那天，两边的 bit 位置就会开始漂。
#:   (字段名, 起始 bit, 位宽)
FIELDS = (
    ("opcode",  0,  7),
    ("rd",      7,  5),
    ("xs2",    12,  1),
    ("xs1",    13,  1),
    ("xd",     14,  1),
    ("rs1",    15,  5),
    ("rs2",    20,  5),
    ("funct7", 25,  7),
)

#: 寄存器字段位宽（5bit = RISC-V 通用寄存器号）—— `rs1`/`rs2`/`rd` 共用。
REG_WIDTH = 5
REG_MAX = (1 << REG_WIDTH) - 1


class WordError(ValueError):
    """指令字层面的失败。越界的字段**直接抛**，不截断 ——
    截断的后果是一个合法但指向别的指令的字，仿真里表现为行为异常而非报错。"""


def parse_opcode(text: Optional[str]) -> int:
    """registry 的 `opcode` 字段 → 7bit 整数。**按二进制整数解析，不补零。**

    `OpSpec.opcode` 保持字符串原样（表里怎么写就怎么存）；这里做的是
    「表的写法 → 接口的写法」这一层转换。
    """
    if not text or not isinstance(text, str):
        raise WordError(f"opcode 为空或类型不对: {text!r}")
    cleaned = text.strip().replace("_", "").replace(" ", "")
    if not cleaned or set(cleaned) - {"0", "1"}:
        raise WordError(f"opcode 不是二进制: {text!r}")
    value = int(cleaned, 2)
    if not 0 <= value < 128:
        raise WordError(f"opcode 超出 7bit: {text!r} -> {value}")
    return value


def opcode_for_family(family: str) -> int:
    """`isa_family` → opcode。未知族响亮失败，不猜。"""
    try:
        return FAMILY_OPCODE[str(family)]
    except KeyError:
        raise WordError(
            f"未知 isa_family: {family!r}（已知: {sorted(FAMILY_OPCODE)}）"
        ) from None


def pack(*, funct7: int, opcode: int, rs1: int = 0, rs2: int = 0, rd: int = 0,
         xd: int = 0, xs1: int = 0, xs2: int = 0) -> int:
    """按 `FIELDS` 打包成 32bit 指令字。"""
    values = {
        "opcode": opcode, "rd": rd, "xs2": xs2, "xs1": xs1, "xd": xd,
        "rs1": rs1, "rs2": rs2, "funct7": funct7,
    }
    word = 0
    for name, shift, width in FIELDS:
        v = values[name]
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < (1 << width):
            raise WordError(
                f"字段 {name} 超出 {width}bit: {v!r}（合法 0..{(1 << width) - 1}）"
            )
        word |= v << shift
    return word


def unpack(word: int) -> Dict[str, int]:
    """32bit 指令字 → 字段 dict。`pack(**unpack(w)) == w` 由测试钉住。"""
    if not isinstance(word, int) or isinstance(word, bool) or not 0 <= word < (1 << 32):
        raise WordError(f"不是 32bit 字: {word!r}")
    return {
        name: (word >> shift) & ((1 << width) - 1)
        for name, shift, width in FIELDS
    }


def to_hex(word: int) -> str:
    """指令字 → `seq.hex` 的一行。**8 位大写 hex，无前缀。**

    §3.0：「`seq.hex` 为 32bit 指令字逐行文本(hex)」。定宽 8 位是为了让人
    肉眼能对齐读，也让 git diff 干净。
    """
    return f"{word & 0xFFFFFFFF:08X}"


def describe(word: int) -> str:
    """给人看的一行解读（`encode --verbose` 用）。"""
    f = unpack(word)
    return (f"{to_hex(word)}  funct7={f['funct7']:07b} rs1={f['rs1']:2d} "
            f"rs2={f['rs2']:2d} rd={f['rd']:2d} "
            f"xd={f['xd']} xs1={f['xs1']} xs2={f['xs2']} "
            f"opcode={f['opcode']:07b}")
