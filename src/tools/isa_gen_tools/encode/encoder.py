"""编码器主流程 —— IR → `seq.hex`（32bit 指令流）+ `reg-init.txt`。

对应文档 §3.1 的 **L3 二进制编码**层：

    L1 场景 DSL ──[isa_gen]──► L2 ISA 事务层 IR ──[本模块]──► L3 32bit（seq.hex）

为什么 L2 / L3 要分成两层（§3.1 的理由）
    · **消费者不同**：TB 执行器消费 IR（要逐条握手与反压，所以需要可读、
      带 `tag` / `binds` / `writes` 语义）；ISS 消费二进制流（只要 32bit）。
      一个文件服务不了两种消费方式。
    · **解耦变更面**：编码表会变（`explain` 里那 16 条前缀不符、6 组同码……），
      分层之后改编码表只重跑本模块，**IR 一个字节都不用动**。

本模块做三件事，按顺序
    1. **寄存器分配**（`regalloc.py`）—— IR 的数值 → 5bit 物理索引 + reg-init
    2. **mask 装配** —— NICE 的 `mask` 走**全局寄存器**，所以编码器要在
       mask 变化时**自动补一条 `group_mask_drv_xn`**（§3.2.1 第 2 条）
    3. **位打包**（`word.py`）—— funct7/flags/opcode 来自注册表，rs1/rs2/rd
       来自分配器，拼成 32bit

不进指令流的条目
    IR 里有两类东西**不该出现在 seq.hex**：
      · **非指令 op**（`wait_done` / `expect_rd` / `mem_init`…）—— §3.2 归为
        时序/观测/数据类，由 TB 的 timer_engine / vseq / preload_engine 消费。
        它们没有 funct7，本来也编不出来。
      · **被跳过是正常路径，不是错误** —— 但**要记 note**，否则"我的指令怎么
        少了 4 条"就只能靠人肉数。本包的一贯纪律：不静默。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..domain.opcode import OpRegistry, OpSpec
from . import word as W
from .regalloc import RegisterAllocator, parse_value, reg_name

#: 更新全局 group_mask 的那条指令名（§3.2.1 第 2 条）。
GROUP_MASK_OP = "group_mask_drv_xn"

#: 允许显式出现在 IR 里、但本编码器**不做特殊处理**的逃生口（§3.2 的
#: `raw_cmd {data64}` —— 仅用于负例：非法 funct7 / 非法 flags 组合）。
RAW_CMD_OP = "raw_cmd"


class EncodeError(ValueError):
    """编码期失败。带 `kind` / `target` / `fix` 三件套，与 `api` 层同形。"""

    kind = "encode_error"

    def __init__(self, message: str, *, target: Any = "", fix: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.target = str(target)
        self.fix = fix

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, "kind": self.kind, "target": self.target,
                "fix": self.fix}


@dataclass
class EncodedItem:
    """一条 IR 条目 → 它的编码结果（或"为什么没编"）。"""

    index: int                     # 在 IR `instructions` 里的位置
    op: str
    tag: str = ""
    word: Optional[int] = None     # None = 不进指令流
    rs1: int = 0
    rs2: int = 0
    rd: int = 0
    mask: str = ""
    #: `nice` / `vnice` —— 决定 opcode（custom-0 / custom-1）。
    #: 清单里要看得见：同一个 funct7 在两条流里的含义不同。
    family: str = ""
    synthesized: bool = False      # True = 编码器补的（group_mask 更新）
    skip_reason: str = ""
    #: IR 里那条的 `operands` 原文 —— 清单要能看到"这一槽放的是什么"
    operands: Dict[str, Any] = field(default_factory=dict)

    @property
    def encoded(self) -> bool:
        return self.word is not None


@dataclass
class EncodeResult:
    items: List[EncodedItem] = field(default_factory=list)
    reg_init: str = ""
    notes: List[str] = field(default_factory=list)
    #: 使能位说要这个操作数、但 IR 里没有的槽。**必须能看见** ——
    #: 编出来的那个字里那一槽是 0（读 x0），而 0 是个合法的操作数，
    #: 静默地编出"读 x0"就是最坏的那种错（仿真里表现为算错，不报错）。
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    #: `{寄存器号: 初值}` —— 清单里把 `x2` 反查成它装载的值用（同 `reg-init.txt`）
    registers: Dict[int, int] = field(default_factory=dict)
    case_name: str = ""
    seed: Any = ""
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def words(self) -> List[int]:
        return [i.word for i in self.items if i.encoded]      # type: ignore[misc]

    def render_seq_hex(self, *, case_name: str = "", seed: Any = "") -> str:
        """`seq.hex` 文本：每行一个 8 位大写 hex（§3.0）。

        **不带注释头** —— ISS 侧要按行读，混进 `#` 会让"读一行"变成
        "先判断这行是不是注释"。溯源与警示在 `case.json` / `reg-init.txt` 里。
        """
        return "".join(W.to_hex(w) + "\n" for w in self.words)

    def render_gap_warnings(self) -> List[str]:
        """有 gap 时的警示行（写进 `reg-init.txt` 的注释块）。

        为什么落在 `reg-init.txt` 而不是 `seq.hex`：后者是 ISS 按行读的纯数据，
        不能混注释；而 `reg-init.txt` 本来就是给人和 ISS 看的对照表，有注释先例。
        """
        if not self.gaps:
            return []
        lines = ["#", "# ⚠ 以下操作数槽**没有填出来**，对应指令字里那一槽是 0："]
        for g in self.gaps:
            lines.append(f"#   [{g.get('index')}] {g.get('op')}.{g.get('slot')} "
                         f"({g.get('enable')}=1) — {g.get('why')}")
        lines.append("#   0 是个合法操作数（x0=0），所以**仿真不会在这里报错**。")
        return lines

    # ── 可读清单 ──────────────────────────────────────────────

    def render_listing(self) -> str:
        """`seq.lst` —— **NICE / VNICE 指令流的人可读视图**。

        与 `seq.hex` **逐行对应**：清单里的 `off` 就是那个字在流里的字节偏移
        （`n × 4`），所以对着 ISS 的 PC 能直接找过来。`seq.hex` 本身是给 ISS
        按行读的纯数据，加不了注释，也读不出"这是哪条指令" —— 这份补上那件事。

        每一列都不是装饰：`isa` 决定 opcode（nice=custom-0 / vnice=custom-1），
        `xd/xs1/xs2` 决定哪几个寄存器字段**有意义**（置位才有号），
        `rs1/rs2/rd` 同时给出号和它装载的值（值来自 `reg-init.txt` 那张表）。

        不进指令流的条目（非指令 op）另起一段列在后面 —— 它们**不在**
        `seq.hex` 里，混进主清单会让人以为流里有它们。
        """
        lines: List[str] = [
            "# seq.lst —— NICE / VNICE 指令流（可读视图）",
            f"# case: {self.case_name or '<unnamed>'}   seed: {self.seed}   "
            f"{len(self.words)} 条指令",
            "# 与 seq.hex 逐行对应：第 n 个字的 off = n*4，可对着 ISS 的 PC 找。",
            "# `isa` 决定 opcode —— nice = custom-0（0001011）/ vnice = custom-1（0101011）。",
            "# rs1/rs2/rd 只有使能位（xd/xs1/xs2）置位时才有号；值来自 reg-init.txt 那张表。",
            "#",
            f"{'off':>6}  {'word':8}  {'isa':5}  {'op':28}  {'tag':4}  {'mask':8}  "
            f"{'xd':>2} {'xs1':>3} {'xs2':>3}  {'rs1':16} {'rs2':16} {'rd':5}  operands",
        ]

        # 哪些 (IR 条目, 槽) 是空的 —— 清单里**当场标出来**，
        # 不然 `x0` 看起来像"故意读 x0"，而它其实是"这一槽没填出来"。
        gap_at = {(g.get("index"), g.get("slot")) for g in self.gaps}

        word_idx = 0
        for it in self.items:
            if not it.encoded:
                continue
            off = word_idx * 4
            word_idx += 1
            f = W.unpack(it.word)                                  # type: ignore[arg-type]
            ops = it.operands or {}
            operands = " ".join(f"{k}={v}" for k, v in ops.items()) or "-"
            if (it.index, "rs1val") in gap_at:
                operands += "  ⚠rs1val 未填"
            if (it.index, "rs2val") in gap_at:
                operands += "  ⚠rs2val 未填"
            lines.append(
                f"{off:#6x}  {W.to_hex(it.word):8}  {it.family or '?':5}  "
                f"{it.op:28}  {it.tag or '-':4}  {it.mask or '-':8}  "
                f"{f['xd']:>2} {f['xs1']:>3} {f['xs2']:>3}  "
                f"{self._reg_cell(f['xs1'], f['rs1']):16}  "
                f"{self._reg_cell(f['xs2'], f['rs2']):16}  "
                f"{self._reg_cell(f['xd'], f['rd']):5}  {operands}"
            )

        skipped = [i for i in self.items if not i.encoded]
        if skipped:
            lines += ["#", f"# 以下 {len(skipped)} 条**不进 seq.hex**"
                           f"（非指令 op —— 由 TB 侧消费，没有 funct7）："]
            for i in skipped:
                lines.append(f"#   [{i.index}] {i.op}"
                             f"{'  ' + i.skip_reason if i.skip_reason else ''}")

        warnings = self.render_gap_warnings()
        if warnings:
            lines += ["#"] + warnings
        return "\n".join(lines) + "\n"

    def _reg_cell(self, enabled: int, index: int) -> str:
        """`x2=0x4000` / `-`（使能位没置位时那个字段没有意义）。"""
        if not enabled:
            return "-"
        value = self.registers.get(index)
        return f"x{index}" if value is None else f"x{index}=0x{value:X}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "words": self.words,
            "seq_hex": self.render_seq_hex(),
            "listing": self.render_listing(),
            "reg_init": self.reg_init,
            "notes": list(self.notes),
            "gaps": [dict(g) for g in self.gaps],
            # `{寄存器号: 初值}` —— 界面要显示 `x2=0x4000` 而不是光一个 `x2`，
            # 所以给结构化的一份（`reg_init` 是给人读的文本，解析它没有道理）
            "registers": {str(k): v for k, v in sorted(self.registers.items())},
            "stats": dict(self.stats),
            "items": [
                self._item_dict(i) for i in self.items
            ],
        }

    @staticmethod
    def _item_dict(i: "EncodedItem") -> Dict[str, Any]:
        """一条条目 → dict。

        `flags`（xd/xs1/xs2）**从编好的字里解出来**，不是另外再算一遍 ——
        界面侧只经 bridge 拿这份 dict（不许 import 本包），所以位域必须在这里
        摊平给它；让界面自己按 bit 位置解，就是把位布局抄了第二份。
        """
        flags: Dict[str, int] = {}
        if i.encoded:
            f = W.unpack(i.word)                                   # type: ignore[arg-type]
            flags = {"xd": f["xd"], "xs1": f["xs1"], "xs2": f["xs2"]}
        return {"index": i.index, "op": i.op, "tag": i.tag,
                "encoded": i.encoded,
                "word_hex": W.to_hex(i.word) if i.encoded else "",
                "isa": i.family, "mask": i.mask, "flags": flags,
                "rs1": i.rs1, "rs2": i.rs2, "rd": i.rd,
                "operands": dict(i.operands),
                "synthesized": i.synthesized,
                "skip_reason": i.skip_reason}


def _operand(inst: Dict[str, Any], key: str) -> Optional[Any]:
    ops = inst.get("operands")
    if not isinstance(ops, dict):
        return None
    return ops.get(key)


def _instruction_word(spec: OpSpec, *, rs1: int, rs2: int, rd: int) -> int:
    """一条已分配好寄存器的指令 → 32bit 字。"""
    if not spec.has_encoding:
        raise EncodeError(
            f"指令 {spec.name!r} 没有编码信息（funct7/flags 缺失）",
            target=spec.name,
            fix="检查编码表该行；标了 `deferred` 的指令本就不该进 IR",
        )
    xd, xs1, xs2 = spec.flags                                    # type: ignore[misc]
    opcode = W.parse_opcode(spec.opcode) if spec.opcode else \
        W.opcode_for_family(spec.isa_family.value)
    return W.pack(funct7=spec.funct7, opcode=opcode,          # type: ignore[arg-type]
                  rs1=rs1, rs2=rs2, rd=rd, xd=xd, xs1=xs1, xs2=xs2)


def encode_ir(ir: Dict[str, Any], registry: OpRegistry, *,
              auto_group_mask: bool = True,
              allow_inconsistent_flags: bool = False) -> EncodeResult:
    """IR（dict）→ `EncodeResult`。

    `auto_group_mask=False` 关掉"mask 变化时补 `group_mask_drv_xn`"——
    只在定向构造非法序列时用（那时你要精确控制指令流里有什么）。

    `allow_inconsistent_flags` —— §3.2.1 第 5 条说 flags 与 operands 的
    一致性**可被显式打破**（xs1/xs2 置位但 rsXval 缺失，期望 `cmd_int[0]`）。
    那种负例必须**显式**要：默认（False）遇到就不一致**直接报错**。

    为什么默认报错而不是记 note：这个不一致有两种来源，长相一模一样 ——
      · 故意的负例（§3.2.1 第 5 条）
      · **生成器漏填**（实测 `npu_gemm` 34 条里 24 条缺 `rs2val`，
        因为 `compile/templates.py:_instruction` 只填 rs1val）
    把它当负例放过，第二种情况就会编出一堆 `rs=0`（读 x0 = 0）的指令 ——
    ISS 拿到 0 当基地址，结果全错**而不报错**。所以：要么显式说是负例，
    要么就让它响亮地失败。
    """
    if not isinstance(ir, dict):
        raise EncodeError("IR 必须是 dict（`seq.ir.json` 解析后的对象）")

    instrs = ir.get("instructions")
    if not isinstance(instrs, list):
        raise EncodeError("IR 缺 `instructions` 数组", target="instructions",
                          fix="这份 IR 是不是旧版本？v0 的 IR 顶层是数组，"
                              "现版本是对象且指令在 `instructions` 下")

    result = EncodeResult()
    ra = RegisterAllocator()
    current_mask: Optional[str] = None

    for idx, inst in enumerate(instrs):
        if not isinstance(inst, dict):
            raise EncodeError(f"instructions[{idx}] 不是对象", target=f"instructions[{idx}]")
        op = str(inst.get("op", "")).strip()
        tag = str(inst.get("tag", "") or "")

        if not op:
            raise EncodeError(f"instructions[{idx}] 缺 `op`", target=f"instructions[{idx}]")

        if op == RAW_CMD_OP:
            # 逃生口：本编码器不做特殊处理 —— 它要的是"非法位组合"，
            # 而那正是 `pack` 会拒绝的东西。记 note 让人看见它被跳过了。
            result.notes.append(
                f"[{idx}] 跳过 `{RAW_CMD_OP}`（负例逃生口，本编码器不装配）"
            )
            result.items.append(EncodedItem(idx, op, tag, skip_reason="raw_cmd"))
            continue

        spec = registry.find(op)
        if spec is None:
            raise EncodeError(
                f"IR 里的 op {op!r} 不在编码表里",
                target=op,
                fix="核对拼写；或它属于尚未接入的部分（Cfg / 精度表）",
            )

        if not spec.is_instruction:
            # 非指令 op（时序 / 观测 / 数据 / 配置）—— 属 TB 侧，不进指令流
            result.items.append(EncodedItem(
                idx, op, tag, family=spec.isa_family.value,
                skip_reason="非指令 op（TB 侧协议，不进 seq.hex）"))
            continue

        mask = inst.get("mask")

        # ── mask 装配（§3.2.1 第 2 条）──────────────────────────
        # NICE 的目标核集合走**全局 group_mask 寄存器**，指令自带不了；
        # 所以 mask 一变，编码器必须在前面补一条 group_mask_drv_xn。
        #
        # VNICE 不走这条 —— 它由指令自带 6b_grp_mask 表达（在那条的
        # operands 里），不需要全局寄存器。
        if (auto_group_mask and mask is not None
                and spec.isa_family.value == "nice"
                and op != GROUP_MASK_OP and str(mask) != current_mask):
            gm = registry.find(GROUP_MASK_OP)
            if gm is None:
                raise EncodeError(
                    f"编码表里没有 {GROUP_MASK_OP!r}，无法更新全局 mask",
                    target=GROUP_MASK_OP, fix="检查 ops.registry.json")
            gm_idx = ra.alloc_value(parse_value(mask), where=f"[{idx}] group_mask")
            gm_rd = ra.alloc_result(where=f"[{idx}] group_mask") if gm.flags[0] else 0
            result.items.append(EncodedItem(
                index=idx, op=GROUP_MASK_OP, tag="",
                word=_instruction_word(gm, rs1=gm_idx, rs2=0, rd=gm_rd),
                rs1=gm_idx, rd=gm_rd, mask=str(mask), family=gm.isa_family.value,
                synthesized=True, operands={"rs1val": str(mask)}))
            current_mask = str(mask)
            result.notes.append(
                f"[{idx}] mask 变化 → 自动补 `{GROUP_MASK_OP}` = {mask}"
            )
        elif op == GROUP_MASK_OP and mask is not None:
            current_mask = str(mask)

        # ── 寄存器分配 ──────────────────────────────────────────
        xd, xs1, xs2 = spec.flags                                # type: ignore[misc]
        rs1 = rs2 = rd = 0
        where = f"[{idx}] {op}"

        def _operand_for(enabled: bool, key: str, reg: str) -> Optional[int]:
            """取操作数并按需分配寄存器。返回 None = 没有值（使能位决定后果）。"""
            v = _operand(inst, key)
            if enabled:
                if v is None:
                    msg = (f"{where}: {reg}=1 但 operands.{key} 缺失 —— "
                           f"无法编码（编出来会读 x0 = 0）")
                    if not allow_inconsistent_flags:
                        raise EncodeError(
                            msg, target=f"instructions[{idx}]",
                            fix=f"生成器没填 {key}。若这是故意的负例，"
                                f"加 allow_inconsistent_flags=True")
                    result.notes.append(msg)
                    result.gaps.append({
                        "index": idx, "op": op, "slot": key, "enable": reg,
                        "why": "IR 里没有这个操作数（生成侧的 operand_gap）",
                    })
                    return None
                return ra.alloc_value(parse_value(v), where=f"{where}.{reg}")
            if v is not None:
                result.notes.append(f"{where}: {reg}=0 但给了 {key} —— 该值不会被编码")
            return None

        r = _operand_for(bool(xs1), "rs1val", "xs1")
        rs1 = r or 0
        r = _operand_for(bool(xs2), "rs2val", "xs2")
        rs2 = r or 0

        if xd:
            # 结果寄存器**不给初值**：值是执行后才有的（§3.2.1 第 1 条：
            # DUT 内无 RV register file，xd=1 的返回值经 rsp 口观察）
            rd = ra.alloc_result(where=f"{where}.rd")

        result.items.append(EncodedItem(
            index=idx, op=op, tag=tag,
            word=_instruction_word(spec, rs1=rs1, rs2=rs2, rd=rd),
            rs1=rs1, rs2=rs2, rd=rd,
            # 清单要看的四样：族（决定 opcode）、mask、以及那条 IR 的操作数原文
            family=spec.isa_family.value, mask=str(mask or ""),
            operands=dict(inst.get("operands") or {})))

    result.case_name = str(ir.get("name", ""))
    result.seed = ir.get("seed", "")
    result.registers = ra.table()
    result.reg_init = ra.render_reg_init(
        case_name=result.case_name, seed=result.seed)
    warnings = result.render_gap_warnings()
    if warnings:
        result.reg_init += "\n".join(warnings) + "\n"

    result.stats = {
        "ir_items": len(instrs),
        "encoded": len(result.words),
        "skipped": sum(1 for i in result.items if not i.encoded),
        "synthesized": sum(1 for i in result.items if i.synthesized),
        "registers": ra.stats(),
        "notes": len(result.notes),
        "gaps": len(result.gaps),
    }
    return result


# ═══════════════════════════════════════════════════════════════
# 反查（调试用）—— 为什么"身份是四元组不是 funct7"
# ═══════════════════════════════════════════════════════════════

def decode_word(word: int, registry: OpRegistry) -> Dict[str, Any]:
    """32bit 字 → 可能的指令名。

    **可能有多条** —— 这正是 `domain/opcode.py` 模块头讲的那件事：
    身份是 `(funct7, xd, xs1, xs2)`，而 `gtld_drv_vn01` 与 `noc_drv_vn01`
    连 funct7 都撞（文档 XL-02）。所以这个函数返回**候选列表**，
    不假装能唯一确定 —— 唯一确定的那天，是编码表把碰撞修掉的那天。
    """
    f = W.unpack(word)
    hits: List[str] = []
    for spec in registry.instructions():
        if not spec.has_encoding:
            continue
        if spec.funct7 != f["funct7"] or tuple(spec.flags) != (f["xd"], f["xs1"], f["xs2"]):
            continue
        try:
            opcode = W.parse_opcode(spec.opcode) if spec.opcode else \
                W.opcode_for_family(spec.isa_family.value)
        except Exception:                                        # noqa: BLE001
            continue
        if opcode == f["opcode"]:
            hits.append(spec.name)
    return {"fields": f, "hex": W.to_hex(word), "candidates": hits,
            "ambiguous": len(hits) > 1}


__all__ = ["encode_ir", "decode_word", "EncodeResult", "EncodedItem",
           "EncodeError", "GROUP_MASK_OP"]
