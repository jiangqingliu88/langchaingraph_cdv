"""IR 指令条目 —— ISA 事务层的原子。

字段集来自文档 §3.2.1 第 2 条（强制字段）+ §3.8（v0 固定字段）+ §3.14.1（数据通路）：

    强制  {op, tag?, mask, flags:{xd,xs1,xs2}, operands:{rs1val,rs2val}}
    地址  src / dst / src_addr / dst_addr
    数据  binds / writes（ref 符号引用）
    其它  cfg / fault / expect…

**funct7 与 inst_flag 不在 IR 里。** 它们由 op 名经注册表唯一推出 ——
文档原话："不允许在 IR 中手填"。手填就会出现两处真相，而它们一定会漂移。
这一条有测试钉住（`test_ir_shape.py::test_no_encoding_fields`）。

`to_dict()` 是**唯一**给 JSON 键命名的地方
    有它一个就够：`ir.schema.json` 与导出器都从这里对齐。分成两处写，
    迟早出现"schema 说叫 src_addr、代码里写成 srcaddr"这种只有对着样例
    才发现的问题（旧建模引擎的 schema.yaml 就栽在注释指着一个已删掉的模块上）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .errors import DataPathError
from .opcode import Flags3, format_funct7

#: 一条 IR 条目的 JSON 键（顺序即落盘顺序，diff 才稳）
IR_KEYS: Tuple[str, ...] = (
    "op", "tag", "mask", "flags", "operands", "src", "dst",
    "src_addr", "dst_addr", "binds", "writes", "cfg", "fault", "extra",
)


@dataclass(frozen=True)
class Flags:
    """`xd / xs1 / xs2` 三位 —— 它们是**指令身份的一部分**，不只是元数据。

    真实编码表里同一 funct7 下挂着多条指令，全靠这三位区分
    （见 `opcode.py` 模块头）。所以改写 flags 等于**换了一条指令**。
    """

    xd: int = 0
    xs1: int = 0
    xs2: int = 0

    def __post_init__(self) -> None:
        for name in ("xd", "xs1", "xs2"):
            value = getattr(self, name)
            if value not in (0, 1, False, True):
                raise DataPathError(f"{name} 只能是 0 或 1，拿到 {value!r}",
                                    target=name, fix="flags 是三位布尔量")

    @property
    def as_tuple(self) -> Flags3:
        return (int(self.xd), int(self.xs1), int(self.xs2))

    @property
    def text(self) -> str:
        return "，".join(str(v) for v in self.as_tuple)

    @classmethod
    def from_tuple(cls, values: Flags3) -> "Flags":
        return cls(*values)

    def to_dict(self) -> Dict[str, int]:
        return {"xd": int(self.xd), "xs1": int(self.xs1), "xs2": int(self.xs2)}


@dataclass(frozen=True)
class Operands:
    """标量操作数 —— **指令字段**那条通路（文档 §3.14.1）。

    只放字面量（整数或 `0x…` 字符串）。张量一律走 `binds/writes` + `ref`，
    两条通路互不交叉 —— 把张量塞进来会被 `IrInstruction` 挡下。
    """

    rs1val: Optional[Any] = None
    rs2val: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.rs1val is not None:
            out["rs1val"] = self.rs1val
        if self.rs2val is not None:
            out["rs2val"] = self.rs2val
        return out


def _looks_like_a_tensor(value: Any) -> bool:
    """认出"这看起来是张量/批量数据，不该待在指令字段里"。

    只抓两种明确的形状，不做过度判断：
      · `$` 打头的符号引用（IR 里 `$t.img` 就是张量的写法）
      · 字典里带 `ref` 键
    字符串化的数字、`0x…`、普通整数一律放行 —— 它们是标量该有的样子。
    """
    if isinstance(value, str):
        return value.strip().startswith("$")
    if isinstance(value, dict):
        return "ref" in value
    return False


@dataclass(frozen=True)
class IrInstruction:
    """IR 里的一条。frozen —— 生成过程中只造新的，不改旧的。

    不可变是"配对闭合"那道不变式能立住的前提：一条已经是配对组一部分的指令
    没法被谁半路改一跳，就等于配对关系不可能被下游破坏。
    """

    op: str
    tag: str = ""
    mask: str = ""
    flags: Flags = field(default_factory=Flags)
    operands: Operands = field(default_factory=Operands)

    src: Dict[str, Any] = field(default_factory=dict)
    dst: Dict[str, Any] = field(default_factory=dict)
    src_addr: Optional[str] = None
    dst_addr: Optional[str] = None

    binds: Tuple[str, ...] = ()
    writes: Tuple[Any, ...] = ()

    cfg: str = ""
    fault: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.op:
            raise DataPathError("IR 条目缺 op", fix="每条 IR 必须有 op 名")
        self._reject_tensors_in_operands()

    def _reject_tensors_in_operands(self) -> None:
        """§3.14.1 契约：标量走指令字段，张量走内存，两条通路不交叉。"""
        for name in ("rs1val", "rs2val"):
            value = getattr(self.operands, name)
            if _looks_like_a_tensor(value):
                raise DataPathError(
                    f"{self.op} 的 operands.{name} 里出现了张量引用 {value!r}",
                    target=f"{self.op}.{name}",
                    fix="张量走 binds/writes + ref，指令字段只放标量字面量")

    # ── 派生 ──

    @property
    def is_instruction(self) -> bool:
        """True = 真指令（走 INST_DISP）；False = 配置/数据/时序/观测类 op。

        文档 §3.2 那张表里除了 6 类指令，还有配置（csr_write）、数据（mem_init）、
        时序（wait_done）、观测（expect_rd）等 —— 它们同样在 IR 里，但**不进
        指令流**。编码器据此决定要不要给它编 32bit。
        """
        return bool(self.mask) or self.funct7_hint is not None

    @property
    def funct7_hint(self) -> Optional[str]:
        """只在 `extra` 里显式带了编码提示时才有值 —— 正常路径永远是 None。

        留着它是为了"从裸 dict 回读一份历史 IR"时不至于把指令判成非指令；
        它**不参与生成**，生成路径上 funct7 一律由注册表推。
        """
        hint = self.extra.get("_funct7")
        return str(hint) if hint else None

    def with_extra(self, **kwargs: Any) -> "IrInstruction":
        merged = dict(self.extra)
        merged.update(kwargs)
        return IrInstruction(
            op=self.op, tag=self.tag, mask=self.mask, flags=self.flags,
            operands=self.operands, src=dict(self.src), dst=dict(self.dst),
            src_addr=self.src_addr, dst_addr=self.dst_addr,
            binds=self.binds, writes=self.writes, cfg=self.cfg,
            fault=self.fault, extra=merged)

    def with_tag(self, tag: str) -> "IrInstruction":
        return IrInstruction(
            op=self.op, tag=tag, mask=self.mask, flags=self.flags,
            operands=self.operands, src=dict(self.src), dst=dict(self.dst),
            src_addr=self.src_addr, dst_addr=self.dst_addr,
            binds=self.binds, writes=self.writes, cfg=self.cfg,
            fault=self.fault, extra=dict(self.extra))

    # ── 落盘 ──

    def to_dict(self) -> Dict[str, Any]:
        """IR 条目的 JSON 形状 —— **键名只在这里出现一次**。

        空的字段一律省略（不写 `"tag": ""`）：IR 是给人读、给 diff 看的，
        一片空键会把真正有信息的那几个埋掉。
        """
        out: Dict[str, Any] = {"op": self.op}
        if self.tag:
            out["tag"] = self.tag
        if self.mask:
            out["mask"] = self.mask
        if self.flags.as_tuple != (0, 0, 0):
            out["flags"] = self.flags.to_dict()
        operands = self.operands.to_dict()
        if operands:
            out["operands"] = operands
        for key in ("src", "dst"):
            value = getattr(self, key)
            if value:
                out[key] = value
        for key in ("src_addr", "dst_addr"):
            value = getattr(self, key)
            if value:
                out[key] = value
        if self.binds:
            out["binds"] = list(self.binds)
        if self.writes:
            out["writes"] = [dict(w) if isinstance(w, dict) else w
                             for w in self.writes]
        if self.cfg:
            out["cfg"] = self.cfg
        if self.fault:
            out["fault"] = dict(self.fault)
        # `_` 打头的是内部键，不进 IR（见 funct7_hint）。
        # 例外是 `operand_gap`：它**必须**看得见 —— 那正是"这一槽没填出来"
        # 的唯一痕迹，藏起来就等于静默（见 compile/templates.py 的说明）。
        public_extra = {k: v for k, v in self.extra.items()
                        if not str(k).startswith("_")}
        if public_extra:
            out["extra"] = public_extra
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IrInstruction":
        """裸 dict → 条目。**逃生口**：这条路绕开了事务层的配对保证，
        所以 `IrProgram` 会在装进来的时候用兜底断言查一遍（见 `program.py`）。
        """
        flags_raw = data.get("flags") or {}
        operands_raw = data.get("operands") or {}
        return cls(
            op=str(data.get("op", "")),
            tag=str(data.get("tag", "") or ""),
            mask=str(data.get("mask", "") or ""),
            flags=Flags(int(flags_raw.get("xd", 0)), int(flags_raw.get("xs1", 0)),
                        int(flags_raw.get("xs2", 0))),
            operands=Operands(operands_raw.get("rs1val"), operands_raw.get("rs2val")),
            src=dict(data.get("src") or {}),
            dst=dict(data.get("dst") or {}),
            src_addr=data.get("src_addr"),
            dst_addr=data.get("dst_addr"),
            binds=tuple(data.get("binds") or ()),
            writes=tuple(data.get("writes") or ()),
            cfg=str(data.get("cfg", "") or ""),
            fault=dict(data["fault"]) if data.get("fault") else None,
            extra=dict(data.get("extra") or {}),
        )

    def describe(self) -> str:
        """一行摘要 —— 给人看 / 报错时用。"""
        bits = [self.op]
        if self.tag:
            bits.append(f"tag={self.tag}")
        if self.mask:
            bits.append(f"mask={self.mask}")
        if self.flags.as_tuple != (0, 0, 0):
            bits.append(f"flags={self.flags.as_tuple}")
        return " ".join(bits)


def encode_flags_text(flags: Flags, funct7: Optional[int] = None) -> str:
    """调试用：`funct7/flags` 拼成 "000_0000 (0,1,0)" 这种样子。"""
    head = format_funct7(funct7) if funct7 is not None else "?"
    return f"{head} ({flags.text.replace('，', ',')})"
