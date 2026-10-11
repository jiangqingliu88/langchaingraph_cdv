"""**case 建模 → 功能覆盖率方法学** —— 把模型里的覆盖点变成真的 SystemVerilog covergroup。

## 为什么单开这一层

case 模型（`domain/`）**已经把功能覆盖点建模出来了**：维度是归类、字段承载取值、
取值点 `ValuePoint` 是"分母的刻度"、`cross_pair` 声明维度之间要不要一起组合。
但这些一直**只活在模型里**：

  · `analysis/coverage.py` 算的命中率，分母是模型**自己声明的取值点**，分子是
    **case 表里有没有这个取值** —— 它回答的是"用例写全了没有"，**不是**
    "仿真真的打到了没有"。这两个问题差得很远，而只有后者能签核。
  · 全仓唯一的 covergroup 生成器（`executors/coverage/functional_coverage.py`）
    是 **spec 驱动**的骨架（只给 opcode 枚举 bin），**不认识** case 模型。

于是证据链一直显示 `Covergroup/Coverpoint/Cross 模型: 0/4`。这一层补上那个缺的
转换：**模型里的覆盖点 → 能编译、能采样、能被 `vcover` 统计的 covergroup**。

## 方法学（规则只此一份，文档与实现同源）

| 模型里的东西 | 变成 | 为什么 |
|---|---|---|
| 一个 `CaseModel` | **一个** `covergroup cg_<module>` | cross 要求两个 coverpoint 同作用域，所以合一个而不是每维度一个 |
| `Dimension` | 一组 coverpoint（它的每个字段一个） | 维度是归类，不承载取值 |
| `Field` | `coverpoint <field.name>` | **字段名就是接口信号名**（`front` 从 spec 的 interfaces 取，见 `_draft_casemodel`） |
| `ValuePoint`（取值点） | 一个 `bins` | 取值点就是覆盖分母的刻度，一比一 |
| `Field.cover_bins` | bin 的**名字** | 作者能命名就让作者命名（`bins_for` 已实现对齐规则） |
| `CrossPair`（required/optional） | `cross cp_a, cp_b;` | 声明了要一起组合的维度就该有 cross；`forbidden` 是禁止组合，不生成 |

## 两条纪律

**一、生成的 SV 必须能编译。** 所以取值的字面量走**整型投影**（与
`api.run_uvm_tests` 的 `int_value` 同一套）：取值本身是数字就用它，否则用它在
字段里的下标。中文取值 `首拍` 直接写进 `bins x = {首拍};` 是编译错误；投影成下标
则合法，而原取值以注释留在旁边（`bins b0 = {0}; // 首拍`）—— 语义没丢，编译器也没炸。

**二、算不出来就说出来。** 字段一个取值点都没有、cross 引用的维度解不出来、
维度没有字段 —— 这些**不静默跳过**，进 `notes` 记账。一个"看起来生成了、
其实少了一半 bin"的 covergroup 比一个报错的更坏。

## 与 `analysis/coverage.py` 的分工

那一层算的是"**用例写全了没有**"（模型 vs case 表），这一层产出的是
"**仿真打到了没有**"的度量装置（covergroup → vcover）。两者都要有，
但**不能混为一谈** —— 前者的 100% 不代表后者是 100%。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional

from .domain import CaseModel, Field, token_of

#: 能一起组合的交叉级别 —— `forbidden` 是**禁止**组合，不该生成 cross。
CROSSABLE_LEVELS = ("required", "optional")

#: 一个 coverpoint 最多几个 bin —— 超了就截断并记账。
#:
#: 为什么要有上限：覆盖率库的体积与 bin 数成正比，而 `vcover` 报出来的
#: "bin 命中率"在被稀释之后就不再有指导意义（实测 4360 个 bin 命中 64 个 =
#: 1.46%，那个数字对"该补哪条用例"毫无帮助）。枚举/边界取值点本来就不该多；
#: 真多到这个量级，说明取值点声明方式有问题，该记账而不是硬塞。
MAX_BINS_PER_POINT = 64


@dataclass
class CoverBin:
    """一个覆盖仓（`bins <name> = {<value>};`）。"""
    name: str
    value: int                     # 整型投影后的字面量（唯一能进 SV 的东西）
    token: str                     # 模型里的原始取值（进注释，不丢语义）
    boundary: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "value": self.value, "token": self.token,
                "boundary": self.boundary}


@dataclass
class CoverPoint:
    """一个覆盖点（`cp_<signal>: coverpoint <signal> { ... }`）。"""
    signal: str                    # SV 信号名（= 字段名）
    field: str
    dimension: str
    type: str
    bins: List[CoverBin] = _field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"signal": self.signal, "field": self.field,
                "dimension": self.dimension, "type": self.type,
                "bins": [b.as_dict() for b in self.bins],
                "bin_count": len(self.bins)}


@dataclass
class CrossPoint:
    """一个交叉（`cross cp_a, cp_b;`）—— 两个维度一起组合。"""
    name: str
    signals: List[str]
    level: str
    dimensions: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "signals": list(self.signals),
                "level": self.level, "dimensions": list(self.dimensions)}


@dataclass
class CoverageModel:
    """一个 module 的功能覆盖率模型 —— 覆盖点的**声明**，不是命中。"""
    module: str
    covergroup: str
    coverpoints: List[CoverPoint] = _field(default_factory=list)
    crosses: List[CrossPoint] = _field(default_factory=list)
    notes: List[str] = _field(default_factory=list)

    @property
    def bin_count(self) -> int:
        return sum(len(cp.bins) for cp in self.coverpoints)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "module": self.module,
            "covergroup": self.covergroup,
            "coverpoints": [cp.as_dict() for cp in self.coverpoints],
            "crosses": [c.as_dict() for c in self.crosses],
            "coverpoint_count": len(self.coverpoints),
            "bin_count": self.bin_count,
            "cross_count": len(self.crosses),
            "notes": list(self.notes),
        }


# ════════════════════════════════════════════════════════════
# 名字与字面量
# ════════════════════════════════════════════════════════════

def _slug(text: Any) -> str:
    """一段文本 → 只剩 SV 标识符允许的字符，**不加前缀、不保证首字符合法**。

    与 `sv_ident` 分开：`sv_ident` 要给信号名用（首字符不能是数字），而 bin 名
    自己会加 `b_` 前缀 —— 两处都加就成了 `b_b_0`（实测踩过）。
    """
    return re.sub(r"[^0-9A-Za-z_$]+", "_", str(text or "")).strip("_")


def sv_ident(text: Any, fallback: str = "x") -> str:
    """一段文本 → 合法的 SystemVerilog **信号名**。

    非 ASCII 一律折成 `_`（SV 标识符只允许 `[A-Za-z0-9_$]` 且不能以数字开头）。
    折完为空就退到 `fallback` —— **不返回空串**：空串拼进 `coverpoint` 是语法错误，
    而那个错误要到编译时才发现，离这里已经很远。
    """
    s = _slug(text)
    if not s:
        return fallback
    return s if not s[0].isdigit() else f"s_{s}"


def sv_value(token: Any, index: int) -> int:
    """取值 → 能进 `bins = {…}` 的整型字面量。

    与 `api._int_value_of` **同一套投影**（数字优先，否则用下标）。两处必须一致：
    `run_uvm_tests` 把 `int_value` 送进 sequence 当激励，covergroup 拿同一个数
    当 bin —— 激励打的值和覆盖率收的值对不上，闭环就断在中间了。
    """
    try:
        return int(str(token).strip())
    except (TypeError, ValueError):
        return index


def _bin_name(fld: Field, token: str, index: int, used: set) -> str:
    """取值 → bin 名。作者给了 `cover_bins` 就用作者的，否则由取值推导。

    同一个 coverpoint 里重名会**编译不过**（bins 重定义），所以最后统一去重 ——
    两种来源（作者的命名 / 推导的命名）都可能撞，不能只防一边。
    """
    declared = fld.bins_for(token)
    cand = _slug(declared[0]) if declared else ""
    if not cand:
        part = _slug(token)
        # 全非 ASCII 的取值（`首拍`）折完是空串 —— `f"b_{part}"` 会得到 `b_`，
        # 那是个**非法标识符**，要到 vlog 才炸。退到下标：与 `sv_value` 给这个
        # 取值投影出的数**恰好是同一个**（非数字取值就是按下标投影的），
        # 于是 `bins b_0 = {0};` 名与值自洽。
        cand = f"b_{part or index}"
    if cand[0].isdigit():
        cand = f"b_{cand}"
    name, n = cand, 1
    while name in used:
        n += 1
        name = f"{cand}_{n}"
    used.add(name)
    return name


# ════════════════════════════════════════════════════════════
# 模型 → 覆盖点
# ════════════════════════════════════════════════════════════

def coverage_model(model: CaseModel, module_name: str = "dut") -> CoverageModel:
    """`CaseModel` → `CoverageModel`（覆盖点的声明）。

    调用方应当传 **`resolve()` 过**的模型：`cross_pair.dim_a/dim_b` 与联动的取值
    都是 `resolve()` 回填的，没解析过就会少 cross、少 bin（且是**静默**少）。
    这里对没解析的情况记账（见 `notes`）。
    """
    module = sv_ident(module_name or model.object or "dut", "dut")
    cm = CoverageModel(module=module, covergroup=f"cg_{module}")

    for dim in model.dimensions:
        if not dim.fields:
            cm.notes.append(
                f"维度 {dim.key} 没有任何字段 —— 出不了 coverpoint（维度只归类，"
                f"取值在字段上）")
            continue
        for fld in dim.fields:
            cm.coverpoints.append(_coverpoint(dim.key, fld, cm.notes))

    cm.coverpoints = [cp for cp in cm.coverpoints if cp is not None]
    _attach_crosses(model, cm)
    return cm


def _coverpoint(dim_key: str, fld: Field, notes: List[str]) -> Optional[CoverPoint]:
    """一个字段 → 一个覆盖点。取值点为空时**不产**（产了就是空 coverpoint）。"""
    if not fld.name:
        notes.append(f"维度 {dim_key} 下有个字段没有名字 —— 跳过（信号名都没有，"
                     f"生成不出合法的 coverpoint）")
        return None

    points = fld.value_points()
    if not points:
        notes.append(
            f"字段 {fld.qualified} 一个取值点都没有 —— 不出 coverpoint。"
            f"（range 型要给 boundary，enum 型要给 values；不给就无从覆盖）")
        return None

    truncated = len(points) > MAX_BINS_PER_POINT
    if truncated:
        notes.append(
            f"字段 {fld.qualified} 有 {len(points)} 个取值点，超过 "
            f"{MAX_BINS_PER_POINT} 已截断 —— bin 太多会把 vcover 的"
            f"「bin 命中率」稀释到没有指导意义（覆盖分母请按边界声明）")
        points = points[:MAX_BINS_PER_POINT]

    used: set = set()
    bins = [CoverBin(name=_bin_name(fld, p.token, i, used),
                     value=sv_value(p.token, i), token=str(p.token),
                     boundary=bool(p.boundary))
            for i, p in enumerate(points)]
    return CoverPoint(signal=sv_ident(fld.name, "sig"), field=fld.name,
                      dimension=dim_key, type=fld.type, bins=bins)


def _attach_crosses(model: CaseModel, cm: CoverageModel) -> None:
    """`cross_pair` → `cross`。只认能一起组合的级别，解不出来的记账。"""
    by_dim = {cp.dimension: cp for cp in cm.coverpoints}
    for pair in model.cross_pairs:
        if pair.level == "forbidden":
            continue                       # 禁止组合 —— 故意不生成
        if pair.level not in CROSSABLE_LEVELS:
            cm.notes.append(
                f"cross {pair.a}×{pair.b} 的级别 {pair.level!r} 不认识 —— 跳过"
                f"（可组合的级别只有 {', '.join(CROSSABLE_LEVELS)}）")
            continue
        cp_a, cp_b = by_dim.get(str(pair.a)), by_dim.get(str(pair.b))
        if cp_a is None or cp_b is None:
            missing = [d for d, cp in ((pair.a, cp_a), (pair.b, cp_b)) if cp is None]
            cm.notes.append(
                f"cross {pair.a}×{pair.b} 引用了解不出覆盖点的维度 "
                f"{'、'.join(missing)} —— 跳过（那一维没有字段，或者模型没 resolve）")
            continue
        cm.crosses.append(CrossPoint(
            name=f"cx_{cp_a.signal}_{cp_b.signal}", signals=[cp_a.signal, cp_b.signal],
            level=pair.level, dimensions=[cp_a.dimension, cp_b.dimension]))


# ════════════════════════════════════════════════════════════
# 覆盖点 → SystemVerilog
# ════════════════════════════════════════════════════════════

def render_covergroup(cm: CoverageModel) -> str:
    """`CoverageModel` → 可编译的 SystemVerilog covergroup 文本。

    产出**一个** covergroup（cross 要求同作用域），**不自带采样事件** ——
    采样时钟是集成方的事（它才知道该挂哪个时钟/哪个接口）。例化与采样：

        cg_<module> cg = new();
        // 每条用例跑完（或每个事务到达时）
        cg.sample();

    这样切分是有意的：本工具**不认识** testbench 结构（铁律：工具只管自己的
    契约），把时钟写死在这里就等于替集成方做决定，而且多半是错的。
    """
    lines: List[str] = [
        f"// 功能覆盖率点 —— 由 case 模型生成（casemodel_tools.coverage）",
        f"// 一条 = 一个覆盖点；bin 名取自模型的 cover_bins 或取值本身。",
        f"// 采样由集成方负责：`{cm.covergroup} cg = new(); cg.sample();`",
        f"covergroup {cm.covergroup};",
    ]
    if not cm.coverpoints:
        lines.append("    // 模型里没有任何可取值的字段 —— 这个 covergroup 是空的")
    for cp in cm.coverpoints:
        lines.append(f"    cp_{cp.signal}: coverpoint {cp.signal} {{")
        for b in cp.bins:
            note = f"{b.token}（边界）" if b.boundary else b.token
            lines.append(f"        bins {b.name} = {{{b.value}}};  // {note}")
        lines.append("    }")
    for cx in cm.crosses:
        left, right = cx.signals
        lines.append(f"    {cx.name}: cross cp_{left}, cp_{right};  // {cx.level}")
    lines.append("endgroup")
    return "\n".join(lines) + "\n"
