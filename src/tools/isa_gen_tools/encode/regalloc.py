"""寄存器分配器 —— IR 的**符号值** → 5bit 物理索引 + `reg-init` 初值清单。

文档 §3.2.1 第 4 条
    「IR 符号值 → 分配 5bit rs1/rs2 物理索引 → 生成 reg-init 寄存器初值清单，
      与 seq.hex 一并落盘，**专供 ISS 侧**消费；TB/DUT 侧只消费数值、不消费
      寄存器号。**寄存器号冲突由分配器在生成期静态保证。**」

为什么需要它
    IR 里携带的是**数值**（`operands.rs1val = "0x20000"`），而 RISC-V 指令字
    里放的是**寄存器号** —— 两者之间的对应关系丢不得，否则 ISS 拿到一个
    `rs1=3` 却不知道 3 号寄存器里该预置什么。`reg-init.txt` 就是那张对照表。

    为什么不让 TB 侧也用它：TB/DUT 里**没有 RV register file**
    （§3.2.1 第 1 条）—— inst_agent 直接驱动数值。所以寄存器号只有 ISS 关心，
    这份表**只有唯一一个消费者**。这不是巧合，是"数值通路与寄存器通路分开"
    这条设计的结果。

按值去重 —— 也就是"冲突静态保证"的落点
    同一个数值只占一个寄存器号。这样「一个寄存器号对两个不同数值」这件事
    **在类型层面不可能发生**，不需要事后再查一遍冲突。

    §3.2.1 第 4 条那句"寄存器号冲突由分配器在生成期静态保证"就是这个意思。

x0 不可用
    RISC-V 的 x0 恒为 0 且写入被丢弃。分配给 x0 会让 ISS 侧读到 0 而不是
    期望值 —— 这是**静默错**，所以分配器从 x1 起。

负例：flags 与 operands 故意不一致
    §3.2.1 第 5 条：「flags 与 operands 的一致性**可被显式打破** —— xs1/xs2
    置位但对应 rsXval 缺失……期望 `cmd_int[0]`」。

    这是**合法的测试构造**，不是错误。所以分配器不报错、也不自作主张补一个值，
    而是：rs1/rs2 留 0、并记一条 note 让它在产物里看得见
    （本包的一贯做法：不静默，但也别把合法输入当错误）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: RISC-V 通用寄存器里可分配的范围。x0 恒零、写入被丢弃 —— 排除。
FIRST_USABLE = 1
LAST_USABLE = 31

#: ABI 名（`reg-init.txt` 用 x 名，ISS 侧按物理号读，不关心 ABI）
def reg_name(index: int) -> str:
    return f"x{index}"


def parse_value(raw: Any) -> int:
    """IR 里的数值 → int。接受 `"0x20000"` / `0x20000` / `"8192"`。

    不接受 `None`/`""` —— 那是"缺字段"，调用方必须先判存在性
    （负例路径会显式跳过，不会走到这里）。
    """
    if isinstance(raw, bool):
        raise ValueError(f"数值不能是 bool: {raw!r}")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            raise ValueError("数值为空字符串")
        return int(s, 16) if s.lower().startswith("0x") else int(s, 10)
    raise ValueError(f"无法解析的数值: {raw!r}")


@dataclass
class Allocation:
    """一个已分配的寄存器。`value` 为 None = 结果寄存器（xd=1 的 rd）。"""

    index: int
    value: Optional[int] = None
    slots: List[str] = field(default_factory=list)   # 被哪些 (op, role) 用过


class RegisterAllocator:
    """按值去重分配 5bit 物理索引。

    用法::

        ra = RegisterAllocator()
        idx = ra.alloc_value(0x20000)      # 同一个值永远给同一个号
        rid = ra.alloc_result()            # xd=1 的结果寄存器
        ra.table()                         # {index: value} → reg-init.txt
    """

    def __init__(self) -> None:
        self._by_value: Dict[int, Allocation] = {}
        self._results: List[Allocation] = []
        self._next = FIRST_USABLE

    # ── 分配 ──────────────────────────────────────────────────

    def alloc_value(self, value: int, where: str = "") -> int:
        """已知初值的寄存器（rs1/rs2 用）。同值同号。"""
        hit = self._by_value.get(value)
        if hit is not None:
            if where:
                hit.slots.append(where)
            return hit.index

        alloc = Allocation(index=self._take(), value=value,
                           slots=[where] if where else [])
        self._by_value[value] = alloc
        return alloc.index

    def alloc_result(self, where: str = "") -> int:
        """结果寄存器（xd=1 的 rd）。**不给初值** —— 值是执行后才知道的。

        独立于按值去重的那张表：结果寄存器的内容是运行期产物，
        和预置初值是两类东西，混在一起会让 `reg-init.txt` 看起来
        像"结果也被预置了"。
        """
        alloc = Allocation(index=self._take(), value=None,
                           slots=[where] if where else [])
        self._results.append(alloc)
        return alloc.index

    def _take(self) -> int:
        if self._next > LAST_USABLE:
            raise RuntimeError(
                f"寄存器不够用：已分配 {self._next - FIRST_USABLE} 个，"
                f"可用范围 x{FIRST_USABLE}..x{LAST_USABLE}"
            )
        i = self._next
        self._next += 1
        return i

    # ── 产出 ──────────────────────────────────────────────────

    def table(self) -> Dict[int, int]:
        """`{寄存器号: 初值}` —— 只含**有初值**的（rs1/rs2）。"""
        return {a.index: a.value for a in self._by_value.values()}   # type: ignore[misc]

    def result_registers(self) -> List[int]:
        return [a.index for a in self._results]

    def stats(self) -> Dict[str, int]:
        return {
            "values": len(self._by_value),
            "results": len(self._results),
            "used": self._next - FIRST_USABLE,
            "capacity": LAST_USABLE - FIRST_USABLE + 1,
        }

    def render_reg_init(self, *, case_name: str = "", seed: Any = "") -> str:
        """`reg-init.txt` 的文本。**专供 ISS**（§3.0：「寄存器初值映射」）。

        格式刻意做成 ISS 侧零解析成本的样子：一行一条 `xN 0xHEX`，
        `#` 开头是注释。不带表头分隔线 —— 那会让「读第一行就是数据」这件事
        变成一个特例。
        """
        lines = [
            "# reg-init.txt —— 寄存器初值映射（供 ISS）",
            "# 由 isa_gen 的编码器生成；TB/DUT 侧不消费（DUT 内无 RV register file）",
            f"# case: {case_name or '<unnamed>'}   seed: {seed}",
            "#",
            "# reg   value",
        ]
        for index in sorted(self.table()):
            lines.append(f"{reg_name(index):5s} 0x{self.table()[index]:08X}")
        if self._results:
            lines.append("#")
            lines.append("# 以下为结果寄存器（xd=1），初值由执行决定，不预置：")
            lines.append("#   " + " ".join(reg_name(i) for i in self.result_registers()))
        return "\n".join(lines) + "\n"

