"""操作数语义 —— 编码表的 `rs1val` / `rs2val` 那一列**到底要什么**。

为什么需要这一层
    `ops.registry.json` 里每行已经存了那两列的**原文**（`fields.rs1val` /
    `fields.rs2val`），但原文是给人看的位串联写法：

        {14b_reseved,base_addr_in[17:0]}
        {6b_reseved,base_addr_wt[17:0]}
        全局 base_addr_gdram[35:4]
        【scalar_in1】

    生成器要回答的是「这个槽该放哪个对象」，光有字符串答不了 —— 得先把
    它翻成结构化的语义。本模块就是那次翻译。**不猜**：认不出的形态归到
    `special`，由调用方响亮失败，不用一个"差不多的"解释糊过去。

三种真实形态（实测 95 条指令全部落在这三类里）
    1. **两个独立对象**（多数）
       `gemm_drv_xn`: rs1=`base_addr_in` rs2=`base_addr_wt`
    2. **一个 44bit 地址拆成两半**（tld / gspe 一族）
       `tld_drv_xn`: rs1=`base_addr_lmem[17:0]` rs2=`base_addr_gmem[28:0]`
       —— 这两槽**不是两个对象**，是同一个地址的低位/高位（§3.12.2 T4）
    3. **一个地址 + 一个标量**
       `bc_drv_xn`: rs1=`base_addr_out` rs2=`scalar_in`

    形态 2/3 本模块**认得出来但标成不支持** —— 认出来是为了能给出
    "这是拆地址，不是漏填"这种准确的报错，而不是一句"格式不认识"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

#: `base_addr_XXX` 里这些 XXX 是**地址的一半**（存储体/半字），不是对象名。
#: 见 §3.12.2 T4：local / global 两半由 rs1val、rs2val 拼出来。
ADDR_PART_NAMES = frozenset({
    "lmem", "gmem", "gdram", "ldram", "dram", "rs1", "rs2",
})

#: 编码表用的角色名 → DSL `alloc[].role` 的写法。
#: 表里写 `wt`、DSL 里写 `wgt` —— 只差一个字母，但认不出来就是"找不到对象"。
ROLE_ALIASES: Dict[str, str] = {
    "wt": "wgt",
}

#: `base_addr_XXX[hi:lo]`，也认不带后缀的 `base_addr[hi:lo]`（NoC 的高位段）。
#: 那个不带后缀的形式是**地址的另一段**，不是另一个对象 —— 必须一起抓出来，
#: 否则 `{6b_reserved, 4b_src_core_id, base_addr[43:40], base_addr_src[17:0]}`
#: 会只剩后半段，前半段被静默丢掉。
_FRAG = re.compile(r"base_addr(?:_([A-Za-z_]\w*))?\s*\[(\d+)\s*:\s*(\d+)\]")
#: 编码表里 reserved **两种拼法并存**：`ctrl`/`noc`/`glsu` 写 `reseved`
#: （少一个 r），`tmu`/`mpu`/`vpu` 写 `reserved`。只认一种的话，
#: "高位保留几位"会时对时错 —— 那是位域整体左移级别的错，必须两种都认。
_RESERVED = re.compile(r"(\d+)\s*b?_(?:reserved|reseved)", re.I)
#: 除地址段与保留段之外，还允许出现的**无意义装饰**词。
_NOISE = re.compile(r"[\s,{}]|本核|全局", re.I)


@dataclass(frozen=True)
class OperandSpec:
    """一个操作数槽要什么。

    `kind` 取值：
      · `none`      —— 这一槽不用（原文是 `/` 或空）
      · `addr`      —— **一个地址对象**，`name` 是要去 `alloc` 里找的角色
      · `addr_part` —— 地址的一半（形态 2），**本版本不支持**
      · `scalar`    —— 字面量（形态 3），**本版本不支持**
      · `mask`      —— `core_mask` 这类非地址字段，**本版本不支持**
      · `cfg`       —— `address of cfg_reg` 那种复合字段，**本版本不支持**
      · `special`   —— 认不出的写法（**不猜**）
    """

    kind: str
    name: str = ""
    hi_reserved: int = 0
    lo: int = 0
    bits: int = 0
    raw: str = ""

    @property
    def fillable(self) -> bool:
        """生成器能不能填这一槽（**前提是事务显式声明了它绑哪个角色**）。

        · `none` / `mask`      —— 能（不需要对象，或从事务的 mask 取）
        · `addr`               —— 能（单个地址段，低位从 0 起）
        · `addr_part` 单段     —— 能（`lmem[17:0]` / `gdram[35:4]` 这种：
                                  低位可以不是 0，按 `lo` 右移后取 `bits` 位）
        · `addr_part` **多段** —— **不能**。`base_addr[43:40]` + `base_addr_src[17:0]`
                                  要按 T4 把同一个地址的两段摆到不同位置，
                                  不是"填一个值"能表达的。
        · `scalar` / `cfg` / `special` —— 不能
        """
        if self.kind in ("none", "mask", "addr"):
            return True
        if self.kind == "addr_part":
            return self.bits > 0          # bits==0 = 多段拼接
        return False

    @property
    def role(self) -> str:
        """要去找的角色名（已套用 `ROLE_ALIASES`）。"""
        return ROLE_ALIASES.get(self.name, self.name)

    def field(self, address: int) -> int:
        """一个地址 → 这一槽该放的**字面值**。

        `base_addr_gdram[35:4]` 这种：字段装的是地址的 [35:4] 位，
        所以先右移 `lo` 再按 `bits` 截断。地址超出该字段能表示的范围**抛** ——
        截断会静默把地址搬走。
        """
        if self.kind == "none":
            return 0
        if address >> (self.lo + self.bits):
            raise ValueError(
                f"地址 0x{address:X} 超出 [{self.lo + self.bits - 1}:{self.lo}] "
                f"能表示的范围（{self.bits}bit，右移 {self.lo}）"
            )
        return (address >> self.lo) & ((1 << self.bits) - 1)

    def describe(self) -> str:
        if self.kind == "none":
            return "不用"
        if self.kind == "mask":
            return "核心掩码（从事务的 mask 填）"
        if self.kind == "addr":
            return (f"地址对象 name={self.name}"
                    f"（[{self.bits - 1}:0]，高位保留 {self.hi_reserved}）")
        if self.kind == "addr_part":
            if self.bits:
                return (f"地址对象 name={self.name}"
                        f"（[{self.lo + self.bits - 1}:{self.lo}]，需事务显式声明角色）")
            return "多段拼接地址（本版本不支持）"
        return f"{self.kind}（本版本不支持）"


def _clean(text: str) -> str:
    """去掉给人看的装饰：全角方括号、换行、多余空格。"""
    return (text or "").replace("【", "").replace("】", "") \
                       .replace("\n", " ").strip()


def parse_operand(raw: str) -> OperandSpec:
    """编码表一格的原文 → `OperandSpec`。

    **只认最简单的那种形态**（一个地址段、低位从 0 起、其余是保留位）：

        {14b_reseved, base_addr_out[17:0]}    → addr, role=out, 18bit, 高位保留 14

    任何**复合**写法一律归 `addr_part`（不支持）—— 包括：
        · 一个地址拆成两半（`_lmem[17:0]` + `_gmem[28:0]`，tld 一族）
        · 同一/不同地址的多段拼接（NoC 的 `base_addr[43:40]` + `base_addr_src[17:0]`）
        · 低位不从 0 起（片段落在字中间）
        · 混了别的东西（`4b_src_core_id`）

    **宁可归类到"不支持"，也不要漏读一段。** 漏读的后果是把错误的高位当地址
    送进仿真 —— 表现是数据搬到别处，不报错。
    """
    text = _clean(raw)
    if not text or text == "/":
        return OperandSpec("none", raw=raw)

    matches = list(_FRAG.finditer(text))
    if matches:
        # 去掉所有地址段 + 保留段 + 装饰词之后**还剩什么**
        residue = _FRAG.sub(" ", text)
        residue = _RESERVED.sub(" ", residue)
        residue = _NOISE.sub("", residue)

        first = matches[0]
        hi, lo = int(first.group(2)), int(first.group(3))
        m = _RESERVED.search(text)
        hi_res = int(m.group(1)) if m else 0

        # 单段：一个地址字段（名字是角色、还是 lmem/gmem 这种存储侧名，都算）
        single = (len(matches) == 1 and bool(first.group(1)) and not residue)
        if single:
            kind = "addr" if (lo == 0 and first.group(1) not in ADDR_PART_NAMES) \
                else "addr_part"
            return OperandSpec(kind, name=first.group(1), hi_reserved=hi_res,
                               lo=lo, bits=hi - lo + 1, raw=raw)

        # 多段拼接（或混了别的东西）—— `bits=0` 表示"填不了"
        names = sorted({m.group(1) for m in matches if m.group(1)})
        return OperandSpec("addr_part", name=names[0] if names else "",
                           hi_reserved=hi_res, raw=raw)

    head = text.split(",")[0].split(":")[0].strip()

    # `rs1val[31:16]: address of cfg_reg` 那种复合字段
    if "address of" in text.lower() or "cfg_reg" in text.lower():
        return OperandSpec("cfg", name=head, raw=raw)
    if "core_mask" in text:
        return OperandSpec("mask", name="core_mask", raw=raw)
    if text.lower().startswith("scalar") or "write_value" in text.lower():
        return OperandSpec("scalar", name=head, raw=raw)

    return OperandSpec("special", name=head, raw=raw)


def parse_operands(fields: Optional[Dict[str, str]]) -> Dict[str, OperandSpec]:
    """`OpSpec.fields` → `{"rs1val": OperandSpec, "rs2val": OperandSpec}`。"""
    fields = fields or {}
    return {slot: parse_operand(fields.get(slot, "")) for slot in ("rs1val", "rs2val")}
