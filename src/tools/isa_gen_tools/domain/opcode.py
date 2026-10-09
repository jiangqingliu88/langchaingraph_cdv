"""op 注册表 —— 指令的**身份**与元数据。

一个必须说清楚的坑：身份不是 funct7
    直觉上"一条指令 = 一个 funct7"，但读真实编码表（`HM056_V2_ISA_Pre_Drv`）
    之后发现**同一 funct7 下挂着多条指令**，靠 `xd/xs1/xs2` 三位区分：

        noc_drv_dst_xn  001_0000  (0,0,1)
        noc_drv_src_xn  001_0000  (0,1,1)      ← 同 funct7，同 opcode
        vv_v_drv_xn     101_1000  (0,1,0)
        vvv_v_drv_xn    101_1000  (0,1,1)
        sync_drv_xn     000_0100  (1,0,0)
        fast_sync_drv_xn 000_0100 (0,0,0)

    所以身份是 `(funct7, (xd, xs1, xs2))` 这个四元组。把身份只记成 funct7，
    编码器就会把 dst 版编成 src 版 —— 而且是在**语义层**错，仿真里表现为
    数据搬错方向，不是报错。

    还有一类**消不掉**的碰撞（文档标为 XL-02）：glsu 的
    `tld_drv_xn` 与 `gtld_drv_xn` 同为 `010_0001` 且 flags 也相同，
    靠地址段（local / global）区分；更麻烦的是 `gtld_drv_vn01` 的 funct7 是
    `001_0100`，与 `noc_drv_vn01` **完全撞车**（跨类）。

    这类**不做静默去重**。`OpRegistry.collisions()` 把它们捞出来，
    `api.run_explain` 原样吐给人看 —— 替编码表做判断是错的，
    假装它不存在更错。

注册表是**数据**（`schema/ops.registry.json`），不是代码
    加一条指令是 JSON 编辑 + schema 校验，git diff 里看得见。
    编码器（v1）直接读这张表的 funct7，一行代码都不用改 —— 这就是
    "编码表唯一来源、变更只影响编码器模块"那条设计意图的落点。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .errors import RegistryError

#: `(xd, xs1, xs2)` 三元组
Flags3 = Tuple[int, int, int]


class OpClass(IntEnum):
    """指令大类 —— **就是 funct7 的高 3 位**（文档 §3.2 的七类）。

    从 funct7 推而不是另存一个字段：两份数据能对不上的地方就一定会对不上。
    """

    CONTROL = 0b000
    NOC = 0b001
    GLSU = 0b010
    TMV = 0b011
    MPU = 0b100
    VPU = 0b101

    @property
    def title(self) -> str:
        return {"control": "Control", "noc": "NoC", "glsu": "GLSU", "tmv": "TMV",
                "mpu": "MPU", "vpu": "VPU"}[self.name.lower()]


class IsaFamily(str, Enum):
    """两套指令族 —— 编码表里分成两个 sheet 段，opcode 也不同。

    NICE  = `xn` 后缀，走全局 `group_mask` 寄存器选核（opcode 1011 = RV custom-0）
    VNICE = `vn01`/`vn11` 后缀，指令自带 `6b_grp_mask`（opcode 101011 = custom-1）
    """

    NICE = "nice"
    VNICE = "vnice"


class OpRole(str, Enum):
    """这条指令在事务里扮演什么角色。

    `PRE` 必须与某条 `DRV` 配对（文档 §3.11 的"前置条件"列）；
    `LONE` 自足（如 `group_mask_drv_xn`、`sync_drv_xn`）。
    配对关系**不在这一层强制** —— `domain.transaction.Transaction` 才是
    让不配对变得不可表达的地方。
    """

    PRE = "pre"
    DRV = "drv"
    LONE = "lone"


class MaskSemantics(str, Enum):
    """这条指令选核靠什么（文档 §3.2.1 第 2 条）。

    NICE 以**全局 group_mask 寄存器**为当前值（编码器在 mask 变化时自动生成
    `group_mask_drv_xn` 更新）；VNICE 由**指令自带 6b_grp_mask** 表达。
    两者在 IR 写法上统一为显式 `mask`，由编码器负责具体装配 —— 所以这一位
    只影响编码，不影响 IR 形状。
    """

    GLOBAL = "global"      # NICE：读全局 group_mask 寄存器
    INLINE_6B = "inline"   # VNICE：指令内 6b_grp_mask


class PairingKind(str, Enum):
    """配对形态（文档 §3.11）。"""

    NONE = "none"
    PRE_DRV = "pre_drv"        # pre 必须先于 drv，如 gemm_out_org_pre → gemm
    DST_SRC = "dst_src"        # 强配对且**中间不许插别的指令**：noc_pair_txn


def parse_funct7(text: str) -> Optional[int]:
    """`"000_0000"` → `0`；`"/"` / 空 → None。

    编码表里 funct7 写成 `nnn_nnnn`（3 位类前缀 + 4 位序号），下划线只是
    给人分段看的，去掉后是 7 位二进制。**不认十六进制** —— 表里也没有，
    多一种写法就多一种对不上的可能。
    """
    if text is None:
        return None
    cleaned = str(text).strip().replace("_", "").replace(" ", "")
    if not cleaned or cleaned == "/":
        return None
    if len(cleaned) != 7 or set(cleaned) - {"0", "1"}:
        raise RegistryError(f"funct7 必须是 7 位二进制（形如 000_0000），拿到 {text!r}",
                            target="funct7", fix="检查编码表该行的 funct7 列")
    return int(cleaned, 2)


def format_funct7(value: Optional[int]) -> str:
    """`0` → `"000_0000"`（回写给人看的那种）。"""
    if value is None:
        return ""
    return f"{value:07b}"[:3] + "_" + f"{value:07b}"[3:]


def parse_flags(text: str) -> Optional[Flags3]:
    """`"0，1，0"` → `(0, 1, 0)`。编码表用的是全角逗号，也认半角。"""
    if text is None:
        return None
    cleaned = str(text).strip().replace("，", ",").replace(" ", "")
    if not cleaned or cleaned == "/":
        return None
    parts = [p for p in cleaned.split(",") if p != ""]
    if len(parts) != 3 or set("".join(parts)) - {"0", "1"}:
        raise RegistryError(f"xd/xs1/xs2 必须是三个 0/1（形如 0，1，0），拿到 {text!r}",
                            target="flags", fix="检查编码表该行的 xd, xs1, xs2 列")
    return int(parts[0]), int(parts[1]), int(parts[2])


# ═══════════════════════════════════════════════════════════════
# 一条指令
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class OpSpec:
    """编码表里的一行。

    字段分三组，别混：
      · **身份**：`name` / `funct7` / `flags` —— 决定"这是哪条指令"
      · **编码**：`opcode` / `inst_flag` —— 编码器（v1）用；v0 只登记不消费
      · **用法**：`role` / `pairing` / `cfg_required` / `mask_semantics` /
        `alignment` / `addressing` / `deferred` / `notes` —— 生成器用它做约束
    """

    name: str
    #: `None` = **非指令 op**（`csr_write` / `wait_done` / `expect_*`…）。
    #: 它们同样是合法的 IR 条目，但不进指令流、没有 funct7。
    #: 用 None 而不是硬塞一个 `OpClass.CONTROL`：塞进去会让 `of_class(CONTROL)`
    #: 把 27 条非指令 op 混进 10 条控制指令里，按类查询当场失去意义。
    op_class: Optional[OpClass]
    isa_family: IsaFamily = IsaFamily.NICE
    funct7: Optional[int] = None
    flags: Optional[Flags3] = None
    opcode: Optional[str] = None

    role: OpRole = OpRole.LONE
    pairing: PairingKind = PairingKind.NONE
    cfg_required: str = ""            # 需要先配哪张 cfg 表（tld_cfg / noc_cfg…）
    mask_semantics: MaskSemantics = MaskSemantics.GLOBAL
    alignment: int = 0                # 字节；0 = 未声明（按事务硬约束推）
    addressing: str = ""              # local / global / spram / dram / ""
    sub_family: str = ""              # VPU 的 V_S / VV_V / VS_V / V_V / M_V
    variants: Tuple[str, ...] = ()    # 兄弟形态（vn01/vn11、xn…）
    deferred: bool = False            # 编码表标了"暂时不做"
    notes: str = ""                   # 文档 ⚠ 的疑点原样带过来
    #: 编码表 `rdval` / `rs1val` / `rs2val` 三列的**原文**（位串联写法）。
    #: 结构化解读见 `domain/operands.py` —— 这里保持原样，是为了让
    #: 「表里到底怎么写的」永远可回溯（`explain` 要能原样吐出来）。
    fields: Mapping[str, str] = field(default_factory=dict)

    @property
    def identity(self) -> Tuple[Optional[int], Optional[Flags3]]:
        """决定"这是哪条指令"的那个四元组（见模块头）。

        funct7 或 flags 缺一个都不是完整身份 —— 缺的那一位用 None 占着，
        这样"信息不全"和"信息齐全但撞车"能分开看。
        """
        return (self.funct7, self.flags)

    @property
    def funct7_text(self) -> str:
        return format_funct7(self.funct7)

    @property
    def is_instruction(self) -> bool:
        """True = 真指令（有指令类、走 INST_DISP）；False = 配置/数据/时序/观测类 op。"""
        return self.op_class is not None

    @property
    def has_encoding(self) -> bool:
        """编码信息齐不齐 —— `run_ops` 靠它告诉人"哪些还不能编码"。"""
        return self.funct7 is not None and self.flags is not None

    @property
    def op_class_from_funct7(self) -> Optional[OpClass]:
        """funct7 高 3 位推出来的类。与 `op_class` 不符时值得警惕。"""
        if self.funct7 is None:
            return None
        try:
            return OpClass(self.funct7 >> 4)
        except ValueError:
            return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "op_class": self.op_class.name.lower() if self.op_class else None,
            "isa_family": self.isa_family.value,
            "funct7": self.funct7_text,
            "flags": list(self.flags) if self.flags else None,
            "opcode": self.opcode,
            "role": self.role.value,
            "pairing": self.pairing.value,
            "cfg_required": self.cfg_required,
            "mask_semantics": self.mask_semantics.value,
            "alignment": self.alignment,
            "addressing": self.addressing,
            "sub_family": self.sub_family,
            "variants": list(self.variants),
            "deferred": self.deferred,
            "notes": self.notes,
            "fields": dict(self.fields),
        }


@dataclass(frozen=True)
class Collision:
    """一个身份上挂了多条指令。

    **这是要给人看的，不是要自动消解的。** 有些是设计如此（靠 flags 区分），
    有些是文档标了的疑点（XL-02），有些看起来就是表里的问题
    （`gtld_drv_vn01` 的 funct7 与 `noc_drv_vn01` 撞车）。
    工具没有立场替编码表做判断 —— 只能把这三种都捞出来，让人去分辨。
    """

    funct7: Optional[int]
    flags: Optional[Flags3]
    names: Tuple[str, ...]
    cross_class: bool

    @property
    def funct7_text(self) -> str:
        return format_funct7(self.funct7)

    def to_dict(self) -> dict:
        return {
            "funct7": self.funct7_text,
            "flags": list(self.flags) if self.flags else None,
            "names": list(self.names),
            "cross_class": self.cross_class,
            "same_flags": True,
        }


# ═══════════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════════

class OpRegistry:
    """名字 → `OpSpec`，外加按身份/类/族的查询。

    构造时**校验但不静默修补**：身份重复不是错误（设计如此），
    但 `name` 重复、funct7 位数不对这类是 —— 那些直接抛 `RegistryError`。
    """

    def __init__(self, ops: Iterable[OpSpec]) -> None:
        self._ops: Dict[str, OpSpec] = {}
        for spec in ops:
            if spec.name in self._ops:
                raise RegistryError(
                    f"op 名重复：{spec.name}",
                    target=spec.name,
                    fix="注册表里同一 name 只能出现一次；是同一个 op 的两种写法吗？")
            self._ops[spec.name] = spec
        if not self._ops:
            raise RegistryError("op 注册表是空的",
                                fix="检查 schema/ops.registry.json 是否被正确加载")

    # ── 查询 ──

    def get(self, name: str) -> OpSpec:
        spec = self._ops.get(name)
        if spec is None:
            near = [n for n in self._ops if name and name.split("_")[0] in n][:5]
            raise RegistryError(
                f"注册表里没有 op {name!r}",
                target=name,
                fix=f"检查拼写；名字相近的有：{near}" if near else "检查拼写")
        return spec

    def find(self, name: str) -> Optional[OpSpec]:
        return self._ops.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._ops

    def __len__(self) -> int:
        return len(self._ops)

    def names(self) -> List[str]:
        return sorted(self._ops)

    def all(self) -> List[OpSpec]:
        return [self._ops[n] for n in self.names()]

    def of_class(self, op_class: OpClass) -> List[OpSpec]:
        """某一类的**真指令** —— 非指令 op 没有类，不会混进来。"""
        return [s for s in self.all() if s.op_class is op_class]

    def instructions(self) -> List[OpSpec]:
        """全部真指令（有编码的那 6 类）。"""
        return [s for s in self.all() if s.is_instruction]

    def non_instructions(self) -> List[OpSpec]:
        """全部非指令 op（§3.2 的配置 / 数据 / 时序 / 观测 / 并发 / 逃生口）。"""
        return [s for s in self.all() if not s.is_instruction]

    def of_family(self, family: IsaFamily) -> List[OpSpec]:
        """某一族的**真指令**。

        NICE / VNICE 是**指令族**（opcode 1011 / 101011 两套）—— 非指令 op
        不在任何一族里，它们的 `isa_family` 只是缺省值占位。
        和 `of_class` 同一个道理：不滤掉的话按族查询会虚高。
        """
        return [s for s in self.all()
                if s.is_instruction and s.isa_family is family]

    def deferred(self) -> List[OpSpec]:
        """编码表标了"暂时不做"的那些 —— 生成器不该选它们。"""
        return [s for s in self.all() if s.deferred]

    def without_encoding(self) -> List[OpSpec]:
        """funct7 或 flags 没填全的 —— `run_ops` 用它回答"哪些还不能编码"。"""
        return [s for s in self.all() if not s.has_encoding]

    def by_identity(self) -> Dict[Tuple[Optional[int], Optional[Flags3]], List[OpSpec]]:
        out: Dict[Tuple[Optional[int], Optional[Flags3]], List[OpSpec]] = {}
        for spec in self.all():
            out.setdefault(spec.identity, []).append(spec)
        return out

    def collisions(self) -> List[Collision]:
        """身份上挂了不止一条指令的，全都捞出来 —— 见 `Collision` 的注释。

        跳过 funct7 缺失的那些（它们不是"撞车"，是"没编完"）。
        """
        found: List[Collision] = []
        for (funct7, flags), specs in sorted(
                self.by_identity().items(), key=lambda kv: (kv[0][0] is None, kv[0][0])):
            if funct7 is None or len(specs) < 2:
                continue
            classes = {s.op_class for s in specs if s.is_instruction}
            found.append(Collision(
                funct7=funct7, flags=flags,
                names=tuple(sorted(s.name for s in specs)),
                # 跨类碰撞最值得警惕：同一个 funct7 前缀本该属于同一个类
                cross_class=len(classes) > 1))
        return found

    def class_mismatches(self) -> List[OpSpec]:
        """声明的类与 funct7 高 3 位推出来的类对不上的。

        读表时会遇到（`gtld_drv_vn01` 声明在 glsu 但 funct7 是 001=NoC 前缀）。
        **不修**，只报 —— 是表的疑点就让它显出来。
        """
        out = []
        for spec in self.all():
            if not spec.is_instruction:
                continue
            derived = spec.op_class_from_funct7
            if derived is not None and derived is not spec.op_class:
                out.append(spec)
        return out
