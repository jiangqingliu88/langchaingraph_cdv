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
| `ValuePoint`（取值点） | 一个 `bins` | 取值点就是覆盖分母的刻度 |
| ↑ 但**给了显式仓时不是一比一** | 多个取值点落进一个仓 | 值域划分（`{[1:7]}`）天然多对一 —— 用例按取值点生成、覆盖率按仓收 |
| `Field.cover_bins` | bin 的**名字** | 作者能命名就让作者命名（`bins_for` 已实现对齐规则） |
| `CrossPair`（required/optional） | `cross cp_a, cp_b;` | 声明了要一起组合的维度就该有 cross；`forbidden` 是禁止组合，不生成 |

## 三条纪律

**一、生成的 SV 必须能编译。** 所以取值的字面量走**整型投影**（与
`api.run_uvm_tests` 的 `int_value` 同一套）：取值本身是数字就用它，否则用它在
字段里的下标。中文取值 `首拍` 直接写进 `bins x = {首拍};` 是编译错误；投影成下标
则合法，而原取值以注释留在旁边（`bins b0 = {0}; // 首拍`）—— 语义没丢，编译器也没炸。

**二、算不出来就说出来。** 字段一个取值点都没有、cross 引用的维度解不出来、
维度没有字段 —— 这些**不静默跳过**，进 `notes` 记账。一个"看起来生成了、
其实少了一半 bin"的 covergroup 比一个报错的更坏。

**三、每个 bin 必须至少有一个取值点能打到。** 这是"激励侧与度量侧同一份分母"
的**准确说法**（不是"一比一"—— 给了显式仓时天然多对一）：

    用例按 `value_points()` 生成（一个取值点一条 test）
    覆盖率按 `bins` 收（一个仓可能盖住好几个取值点）

多对一无害，**空洞致命**：某个仓一个取值点都打不到 → 声明的覆盖率**永远封顶**，
而 covergroup 编译通过、回归跑得过、日志一切正常。由 `run_gaps` 的
`cover_bin_unreachable` 拦 —— 实测踩过：`cluster_id` 写了 4 个显式仓却没给
`boundary`，`RangeField` 退化到 `[min, max]`，c1/c2 永远打不到。

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
    """一个覆盖仓（`bins <name> = {…};` / `illegal_bins <name> = {…};`）。

    三种"内容"（互斥，按下面的顺序渲染）：

      · `lo` 有值  → **区间**：`{[lo:hi]}`（`hi` 为 None 就是 `{[lo:$]}`）
      · `values` 非空 → **集合**：`{0,7,8}`
      · 否则 `value` → **单值**：`{32}`
    """
    name: str
    value: Optional[int] = None    # 整型投影后的单值字面量
    values: List[int] = _field(default_factory=list)   # 多值集合
    lo: Optional[int] = None       # 区间下界
    hi: Optional[int] = None       # 区间上界；None + lo 有值 ⇒ `$`
    token: str = ""                # 模型里的原始写法（进注释，不丢语义）
    boundary: bool = False
    illegal: bool = False

    def literal(self) -> str:
        """`bins` 右边那对花括号里的东西 —— **唯一进 SV 的部分**。"""
        if self.lo is not None:
            return f"[{self.lo}:{'$' if self.hi is None else self.hi}]"
        if self.values:
            return ",".join(str(v) for v in self.values)
        return str(self.value if self.value is not None else 0)

    def as_dict(self) -> Dict[str, Any]:
        out = {"name": self.name, "token": self.token, "boundary": self.boundary,
               "illegal": self.illegal, "literal": self.literal()}
        if self.lo is not None:
            out.update(lo=self.lo, hi=self.hi)
        elif self.values:
            out["values"] = list(self.values)
        else:
            out["value"] = self.value
        return out


@dataclass
class CoverPoint:
    """一个覆盖点（`cp_<signal>: coverpoint <signal> { ... }`）。"""
    signal: str                    # SV 信号名（= 字段名）
    field: str
    dimension: str
    type: str
    cover_id: str = ""             # 文档里的覆盖点编号（CP_xxx），给人对账用
    requirement: str = ""          # 需求编号（REQ-xxx）—— 追溯矩阵的另一头
    #: `stimulus`（事务字段，走 env_cov 通道）/ `dut`（DUT 信号，走 bind 探针）
    source: str = "stimulus"
    width: int = 0                 # dut 通道声明探针端口用；0 = 没声明
    expr: str = ""                 # 采样表达式（dut 通道）；空 = 采同名信号
    bins: List[CoverBin] = _field(default_factory=list)
    illegal_bins: List[CoverBin] = _field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"signal": self.signal, "field": self.field,
                "dimension": self.dimension, "type": self.type,
                "cover_id": self.cover_id, "requirement": self.requirement,
                "source": self.source, "width": self.width, "expr": self.expr,
                "bins": [b.as_dict() for b in self.bins],
                "illegal_bins": [b.as_dict() for b in self.illegal_bins],
                "bin_count": len(self.bins),
                "illegal_bin_count": len(self.illegal_bins)}


@dataclass
class CrossBin:
    """交叉里的一个仓：`bins <name> = binsof(cp_a.<ba>) && binsof(cp_b.<bb>);`

    `when` 是 `{覆盖点名: bin 名}` —— 不用去记它是 a 还是 b，写名字就行。
    """
    name: str
    when: Dict[str, str] = _field(default_factory=dict)
    illegal: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "when": dict(self.when), "illegal": self.illegal}


@dataclass
class CrossPoint:
    """一个交叉 —— 全交叉（`cross cp_a, cp_b;`）或过滤交叉（带 `binsof`）。"""
    name: str
    signals: List[str]
    level: str
    dimensions: List[str]
    bins: List[CrossBin] = _field(default_factory=list)
    source: str = "stimulus"       # 两边共同的采样来源（同作用域才建得起来）
    cover_id: str = ""             # 文档里的交叉编号（X_xxx）—— 追溯用
    requirement: str = ""          # 需求编号（可能是复合的 `REQ-A/B`）

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "signals": list(self.signals),
                "level": self.level, "dimensions": list(self.dimensions),
                "source": self.source, "cover_id": self.cover_id,
                "requirement": self.requirement,
                "bins": [b.as_dict() for b in self.bins],
                "bin_count": len(self.bins)}


@dataclass
class CoverageModel:
    """一个 module 的功能覆盖率模型 —— 覆盖点的**声明**，不是命中。"""
    module: str
    covergroup: str
    coverpoints: List[CoverPoint] = _field(default_factory=list)
    crosses: List[CrossPoint] = _field(default_factory=list)
    notes: List[str] = _field(default_factory=list)

    def by_source(self, source: str) -> List[CoverPoint]:
        return [cp for cp in self.coverpoints if cp.source == source]

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
            "stimulus_coverpoint_count": len(self.by_source("stimulus")),
            "dut_coverpoint_count": len(self.by_source("dut")),
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


def _explicit_bins(raw: Any, used: set, notes: List[str], where: str,
                   illegal: bool = False) -> List[CoverBin]:
    """`cover_bins` / `cover_illegal` 里的**对象条目** → `CoverBin`。

    认识的键：
      `name`     仓名（必填）
      `range`    `[lo, hi]` → `{[lo:hi]}`；`hi` 省略或给 `null` → `{[lo:$]}`
      `from`/`to`  同 `range` 的两种写法（`to` 省略 → `$`）
      `at`       等价于 `values: [at]`
      `values`   显式值集合

    认不出的条目**记账跳过**，不静默 —— 一个"看着写了、其实没生成"的仓，
    要到覆盖率对不上时才会被发现。
    """
    out: List[CoverBin] = []
    for item in (raw if isinstance(raw, list) else [raw]):
        if not isinstance(item, dict):
            continue
        name = sv_ident(item.get("name"), "")
        if not name:
            notes.append(f"{where}：有个{'非法' if illegal else ''}仓没有合法的 name "
                         f"—— 跳过（{item!r}）")
            continue
        if name in used:
            notes.append(f"{where}：仓名 {name} 重复 —— 跳过重复的那个"
                         f"（bins 重定义编译不过）")
            continue
        used.add(name)

        bin_ = CoverBin(name=name, illegal=illegal)
        rng = item.get("range")
        lo, hi = None, None
        if isinstance(rng, (list, tuple)) and rng:
            lo, hi = _opt_int(rng[0]), (_opt_int(rng[1]) if len(rng) > 1 else None)
        elif item.get("from") is not None:
            lo, hi = _opt_int(item.get("from")), _opt_int(item.get("to"))
        if lo is not None:
            bin_.lo, bin_.hi = lo, hi
            bin_.token = f"{lo}:{'$' if hi is None else hi}"
        elif item.get("values") is not None:
            bin_.values = [_as_int(v) for v in
                           (item["values"] if isinstance(item["values"], list)
                            else [item["values"]])]
            bin_.token = ",".join(str(v) for v in bin_.values)
        elif item.get("at") is not None:
            bin_.value = _as_int(item.get("at"))
            bin_.token = str(bin_.value)
        else:
            used.discard(name)
            notes.append(f"{where}：仓 {name} 既没有 range/from/at 也没有 values "
                         f"—— 跳过（没法生成一个空的 bins）")
            continue
        out.append(bin_)
    return out


def _as_int(v: Any) -> int:
    """任意标量 → int。**解不出就给 0 并留给调用方** —— 这里不抛，因为
    `coverage_model` 的契约是"尽力产出 + 记账"，不是"一处不合法就整份没有"。"""
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def _opt_int(v: Any) -> Optional[int]:
    """同上，但 `None` / 空串 → `None`（**不是 0**）。

    区间上界省略是**有意义**的（`{[33:$]}` 表示"33 及以上"），错当成 0 会写成
    `{[33:0]}` —— 一个空区间，编译能过但永远不命中，非法仓就成了摆设。
    """
    if v is None or str(v).strip() == "":
        return None
    return _as_int(v)


def _coverpoint(dim_key: str, fld: Field, notes: List[str]) -> Optional[CoverPoint]:
    """一个字段 → 一个覆盖点。

    两条路：

      · **显式仓**（`cover_bins` 里有对象条目）—— 仓由作者定义，取值点只用来
        给字符串条目命名。`queue_level` 的 0-32 分六档走这条。
      · **取值点** —— 一个取值点一个仓（现有语义）。取值点为空且没有显式仓
        时**不产**（产了就是空 coverpoint）。
    """
    if not fld.name:
        notes.append(f"维度 {dim_key} 下有个字段没有名字 —— 跳过（信号名都没有，"
                     f"生成不出合法的 coverpoint）")
        return None

    where = f"字段 {fld.qualified}"
    used: set = set()
    bins = _explicit_bins(fld.explicit_bins(), used, notes, where)
    illegal = _explicit_bins(fld.cover_illegal, used, notes, where, illegal=True)

    points = fld.value_points()
    if not bins:
        # 没有显式仓才走取值点 —— 两者都有时以显式仓为准（作者写得更具体），
        # 但**要说出来**，不能默默丢掉另一半
        if fld.explicit_bins():
            notes.append(f"{where} 声明了显式仓但一条都没解析出来 —— 退回按取值点分箱")
        if not points:
            notes.append(
                f"{where} 一个取值点都没有、也没有显式覆盖仓 —— 不出 coverpoint。"
                f"（range 型要给 boundary 或 cover_bins，enum 型要给 values）")
            return None
        if len(points) > MAX_BINS_PER_POINT:
            notes.append(
                f"{where} 有 {len(points)} 个取值点，超过 {MAX_BINS_PER_POINT} "
                f"已截断 —— bin 太多会把 vcover 的「bin 命中率」稀释到没有指导意义"
                f"（覆盖分母请按边界声明）")
            points = points[:MAX_BINS_PER_POINT]
        bins = [CoverBin(name=_bin_name(fld, p.token, i, used),
                         value=sv_value(p.token, i), token=str(p.token),
                         boundary=bool(p.boundary))
                for i, p in enumerate(points)]
    elif points:
        notes.append(f"{where} 既有显式覆盖仓又有 {len(points)} 个取值点 —— "
                     f"**以显式仓为准**（取值点仍参与用例生成，只是不各自成仓）")

    width = fld.width or _derive_width(fld, bins)
    if fld.sample == "dut" and not fld.width:
        notes.append(f"{where} 走 DUT 探针但没写 `width` —— 按类型推成 {width} 位"
                     f"（与端口实际宽度不一致时会有截断告警；要零告警就显式写）")
    return CoverPoint(signal=sv_ident(fld.name, "sig"), field=fld.name,
                      dimension=dim_key, type=fld.type, bins=bins,
                      illegal_bins=illegal, cover_id=fld.cover_id,
                      requirement=fld.requirement, source=fld.sample,
                      width=width, expr=fld.sample_expr)


#: 推不出位宽时的兜底 —— **要记账**，不能让一个 32 位的端口悄悄截掉高位。
DEFAULT_WIDTH = 32


def _derive_width(fld: Field, bins: List[CoverBin]) -> int:
    """采样信号的位宽 —— 从字段类型与仓内容推。

    优先级：显式 `width`（调用方处理）→ `range` 的 `max` → 仓里出现过的最大数
    → 1。**不猜"32 位反正够大"**：端口宽度不符会截断，而截断的覆盖点是错的
    数据，编译告警是唯一的提示。
    """
    if fld.max is not None:
        try:
            return max(1, int(float(fld.max)).bit_length())
        except (TypeError, ValueError):
            pass
    hi = 0
    for b in bins:
        for v in ([b.value] if b.value is not None else []) + list(b.values) + \
                 ([b.hi] if b.hi is not None else []):
            if v is not None:
                hi = max(hi, int(v))
    if hi:
        return max(1, hi.bit_length())
    return 1


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
        name = f"cx_{cp_a.signal}_{cp_b.signal}"
        # **交叉的两边必须在同一个 covergroup 里**（cross 要求两个 coverpoint
        # 同作用域）。所以先看两边各从哪采：都在 DUT 里就走探针，都在事务里就
        # 走 env_cov 那条；**一边一边不是同一个作用域，表达不了** —— 记账。
        if cp_a.source != cp_b.source:
            cm.notes.append(
                f"cross {pair.a}×{pair.b} 的两边采样来源不同"
                f"（{cp_a.signal}={cp_a.source} / {cp_b.signal}={cp_b.source}）—— "
                f"跳过：cross 要求两个 coverpoint 同作用域。"
                f"若 {cp_b.signal} 在 DUT 里也按名字可见，把它也标成 `sample: dut`")
            continue
        bins = _cross_bins(pair, [cp_a, cp_b], cm.notes, name)
        cm.crosses.append(CrossPoint(
            name=name, signals=[cp_a.signal, cp_b.signal],
            level=pair.level, dimensions=[cp_a.dimension, cp_b.dimension],
            bins=bins, source=cp_a.source,
            cover_id=pair.cover_id, requirement=pair.requirement))


def _cross_bins(pair: Any, cps: List[CoverPoint], notes: List[str],
                cx_name: str) -> List[CrossBin]:
    """交叉的显式仓 → `CrossBin`。

    `when` 里写**覆盖点名**（信号名），值写**仓名**。两侧都做一次"名字 → 实际仓名"
    的解析：作者可能写 bin 名（`mac`），也可能直接写取值 token（`MAC`）——
    两个都认，认不出就记账跳过。**不能默默生成一个 `binsof(cp.nope)`**：
    那要么编译不过，要么（更糟）被当合法语法收下却永远不命中。
    """
    raw = list(pair.bins or []) + [
        {**b, "illegal": True} if isinstance(b, dict) else b
        for b in (pair.illegal or [])]
    out: List[CrossBin] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        item_name = sv_ident(item.get("name"), "")
        when = item.get("when")
        if not item_name or not isinstance(when, dict):
            notes.append(f"{cx_name}：交叉仓条目缺 name 或 when —— 跳过（{item!r}）")
            continue
        resolved: Dict[str, str] = {}
        bad = False
        for cp in cps:
            want = when.get(cp.signal, when.get(cp.field, when.get(cp.dimension)))
            if want is None:
                notes.append(f"{cx_name}：交叉仓 {item_name} 没给 "
                             f"{cp.signal} 那一侧 —— 跳过")
                bad = True
                break
            found = _match_bin(cp, want)
            if found is None:
                notes.append(
                    f"{cx_name}：交叉仓 {item_name} 在 {cp.signal} 里找不到仓 "
                    f"{want!r}（现有仓：{'、'.join(b.name for b in cp.bins)}）—— 跳过")
                bad = True
                break
            resolved[cp.signal] = found
        if not bad:
            out.append(CrossBin(name=item_name, when=resolved,
                                illegal=bool(item.get("illegal"))))
    return out


def _match_bin(cp: CoverPoint, want: Any) -> Optional[str]:
    """`want` → 这个覆盖点里实际存在的仓名。**bin 名与取值 token 都认。**"""
    w = str(want).strip()
    for b in cp.bins:
        if b.name == w or b.token == w:
            return b.name
    return None


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
        for b in cp.bins + cp.illegal_bins:
            kind = "illegal_bins" if b.illegal else "bins"
            note = f"  // {b.token}" if b.token else ""
            if b.boundary and not b.illegal:
                note = f"  // {b.token}（边界）"
            lines.append(f"        {kind} {b.name} = {{{b.literal()}}};{note}")
        lines.append("    }")
    for cx in cm.crosses:
        left, right = cx.signals
        if not cx.bins:
            lines.append(f"    {cx.name}: cross cp_{left}, cp_{right};  // {cx.level}")
            continue
        lines.append(f"    {cx.name}: cross cp_{left}, cp_{right} {{  // {cx.level}")
        for b in sorted(cx.bins, key=lambda x: x.illegal):
            terms = " && ".join(f"binsof(cp_{sig}.{name})"
                                for sig, name in b.when.items())
            kind = "illegal_bins" if b.illegal else "bins"
            lines.append(f"        {kind} {b.name} = {terms};")
        lines.append("    }")
    lines.append("endgroup")
    return "\n".join(lines) + "\n"


# ════════════════════════════════════════════════════════════
# DUT 探针：采内部/端口信号（第二条采样通道）
# ════════════════════════════════════════════════════════════

#: `sampling:` 块的默认值 —— 与 `config/uvm_templates` 里 bench 的命名一致。
DEFAULT_CLOCK = "clk"
DEFAULT_RESET = "rst_n"
DEFAULT_INSTANCE = "u_cg_probe"


def probe_ports(cm: CoverageModel) -> List[CoverPoint]:
    """探针要声明的端口 —— 就是 `sample: dut` 的那些覆盖点。"""
    return cm.by_source("dut")


def render_probe(cm: CoverageModel, sampling: Dict[str, Any] = None) -> str:
    """`CoverageModel` → 一个 **bind 进 DUT 的探针模块**（含 bind 语句）。

    ## 为什么必须是 bind

    DUT 的**输入端口、输出端口、内部寄存器**，对一个 `bind` 进去的模块来说
    **没有区别** —— 差别只在于"从哪看得见"。而：

      · monitor 的事务通道**只看得到激励侧**：队列水位、依赖类型、发射决策这些
        内部状态与输出端口，它一个都采不到。
      · 层次引用（`u_dut.u_sched.queue_level`）要把 tb_top 的实例名写死，
        换个 bench 就断。

    `bind` 不带这两个问题：挂到**模块**上，每个实例自动带一份；端口连接表达式
    在**目标模块作用域**里求值，所以 `queue_level` 这类内部名直接就能连（实测）。

    ## 采样

    covergroup **不自带事件**，由一句显式的采样驱动：

        always @(posedge clk) if (rst_n) cg.sample();

    复位周期不采（`reset` 给空就不加这个 `if`）—— 复位期间的水位/决策是
    无意义值，采进去只会把 bin 命中率弄脏。

    ## 生成不出探针的两种情形（都记账，由调用方决定）

      · 模型里没有 `sample: dut` 的字段 → 空串（不需要探针）
      · 没有 `sampling.dut_module` → 空串（**bind 的目标都不知道**）
    """
    sampling = sampling or {}
    cps = probe_ports(cm)
    if not cps:
        return ""
    dut_module = sv_ident(sampling.get("dut_module"), "")
    if not dut_module:
        return ""

    clock = sv_ident(sampling.get("clock") or DEFAULT_CLOCK, DEFAULT_CLOCK)
    # 复位给 `null` / 空串 = **不加屏蔽**（有的 DUT 用高有效复位，或者压根不采复位）
    reset = _slug(sampling.get("reset", DEFAULT_RESET)) or ""
    instance = sv_ident(sampling.get("instance") or DEFAULT_INSTANCE,
                        DEFAULT_INSTANCE)
    guard = f"if ({reset}) " if reset else ""

    # 探针的端口 = 时钟 + 复位 + 每个采样信号。**复位也得是端口** ——
    # 它同样活在 DUT 的作用域里，裸写在 `if` 里 probe.sv 当场报
    # `Undefined variable: 'rst_n'`（实测）。
    extra_ports = [clock] + ([reset] if reset else [])

    cg_name = f"{cm.covergroup}_dut"
    guard_macro = f"{cg_name.upper()}_SV"

    out: List[str] = [
        f"`ifndef {guard_macro}",
        f"`define {guard_macro}",
        "",
        "// DUT 信号的功能覆盖率 —— 由 case 模型生成（casemodel_tools.coverage）",
        f"// 用 `bind` 挂到 `{dut_module}` 上：该模块的**每个实例**都会带一份探针。",
        "//",
        "// 为什么走 bind 而不是从 monitor 采：monitor 只看得到**激励侧**，而",
        "// 队列水位 / 依赖类型 / 发射决策这些是内部状态与输出端口 —— 只有从 DUT",
        "// 内部才看得见。端口连接表达式在**目标模块作用域**里求值，所以内部名",
        "// 直接连过来即可。",
        "",
        f"module {cg_name}_probe (",
    ]
    for name in extra_ports:
        out.append(f"  input logic {name},")
    for i, cp in enumerate(cps):
        decl = f"[{cp.width - 1}:0] " if cp.width > 1 else ""
        sep = "," if i < len(cps) - 1 else ""
        src = cp.expr or cp.signal
        note = f"  // {cp.field}" + (f" ← {src}" if cp.expr else "")
        out.append(f"  input logic {decl}{cp.signal}{sep}{note}")
    out += [
        ");",
        "",
        f"  covergroup {cg_name};",
        "    option.per_instance = 1;",
    ]
    for cp in cps:
        out.append(f"    cp_{cp.signal}: coverpoint {cp.signal} {{")
        for b in cp.bins + cp.illegal_bins:
            kind = "illegal_bins" if b.illegal else "bins"
            note = f"  // {b.token}" if b.token else ""
            out.append(f"        {kind} {b.name} = {{{b.literal()}}};{note}")
        out.append("    }")
    for cx in cm.crosses:
        if cx.source != "dut":
            continue
        left, right = cx.signals
        if not cx.bins:
            out.append(f"    {cx.name}: cross cp_{left}, cp_{right};")
            continue
        out.append(f"    {cx.name}: cross cp_{left}, cp_{right} {{")
        for b in sorted(cx.bins, key=lambda x: x.illegal):
            terms = " && ".join(f"binsof(cp_{sig}.{name})"
                                for sig, name in b.when.items())
            kind = "illegal_bins" if b.illegal else "bins"
            out.append(f"        {kind} {b.name} = {terms};")
        out.append("    }")
    out += [
        f"  endgroup",
        "",
        f"  {cg_name} cg = new();",
        "",
        "  // 采样：时钟沿，且**不在复位周期**（复位期间的水位/决策是无意义值）",
        f"  always @(posedge {clock}) {guard}cg.sample();",
        "endmodule",
        "",
        f"bind {dut_module} {cg_name}_probe {instance}(",
    ]
    # 连接表**不能有尾逗号**（`..., )` 是语法错误 —— 实测 vlog 报
    # `near ")": syntax error, expecting .* or '.'`）。所以攒完再 join。
    conns = [f"  .{n}({n})" for n in extra_ports]
    conns += [f"  .{cp.signal}({cp.expr or cp.signal})" for cp in cps]
    out.append(",\n".join(conns))
    out += [");", "", f"`endif  // {guard_macro}", ""]
    return "\n".join(out)


# ════════════════════════════════════════════════════════════
# 功能覆盖率计划（一份 yaml，与 case 模型同批产出）
# ════════════════════════════════════════════════════════════

def coverage_plan(model: CaseModel, cm: CoverageModel,
                  module_name: str = "dut") -> Dict[str, Any]:
    """case 模型 + 覆盖点模型 → **一份完整的功能覆盖率计划**（dict，可 yaml 化）。

    ## 为什么单独一份，而不是散在几处

    覆盖这件事有四张脸，各有各的读者：

        §3 覆盖点     谁在采、采什么、bin 是什么   → 生成 covergroup 的人
        §5 批次       这一批打哪个专题、跑哪个 test → 回归
        §6 种子管理   这一批跑几条才算数            → 回归
        §8 需求追溯   哪条需求被谁验了              → 签核的人

    它们**同源**（都从同一份 case 模型派生），但分散在三四个文件里对账会很痛苦
    ——尤其是"覆盖点声明了 12 个、回归里只跑了 8 条"这种事，只有把两边摆在一张
    表上才看得出来。所以**一起生成**：与 case 模型同批落盘，谁都不许自己算一遍。

    ## 里面有什么是"推"出来的、什么是"抄"的

      · `coverpoints` / `crosses` —— 从模型**推**（bin 明细、来源通道、宽度）
      · `batch.seeds`             —— 模型里**抄**的（作者声明"这一批要跑够几条"）
      · `total_runs`              —— 推：`count + explore`（这才是要跑的总条数）
      · `traceability`            —— 推：按 `requirement` 把覆盖点/交叉/批次串起来
      · `covered_by`              —— 推：**哪个批次覆盖了这个覆盖点**（按专题的
        `dimensions` 反查）。这替代了文档 §4.5 那张"约束 → 覆盖点"表：约束在
        UVM sequence 里，模型看不见；但"哪个批次负责它"是模型能答的。

    ## 说得出来的与说不出来的

    覆盖点没有 `requirement`、批次没有 `test`/`seeds`、交叉没有 `cover_id` ——
    这些**留空并进 `notes`**，不编一个出来。签核表上引用的编号必须是文档里
    那个，编出来的编号比没有更坏。
    """
    notes: List[str] = []
    by_dim: Dict[str, List[str]] = {}
    for th in model.themes:
        for dim in (th.dims or []):
            by_dim.setdefault(dim.key, []).append(th.key)

    coverpoints: List[Dict[str, Any]] = []
    for cp in cm.coverpoints:
        coverpoints.append({
            "cover_id": cp.cover_id,
            "requirement": cp.requirement,
            "dimension": cp.dimension,
            "signal": cp.signal,
            "type": cp.type,
            "source": cp.source,
            "width": cp.width,
            "expr": cp.expr,
            "bins": [b.name for b in cp.bins],
            "illegal_bins": [b.name for b in cp.illegal_bins],
            "bin_count": len(cp.bins),
            "target": 100,
            "covered_by": by_dim.get(cp.dimension, []),
        })
        if not cp.cover_id:
            notes.append(f"覆盖点 {cp.signal} 没有 cover_id —— 追溯矩阵里引用不到它")

    crosses: List[Dict[str, Any]] = []
    for cx in cm.crosses:
        crosses.append({
            "cover_id": cx.cover_id,
            "requirement": cx.requirement,
            "name": cx.name,
            "dimensions": list(cx.dimensions),
            "level": cx.level,
            "source": cx.source,
            "bins": [b.name for b in cx.bins],
            "illegal_bins": [b.name for b in cx.bins if b.illegal],
            "bin_count": len(cx.bins),
            "target": 100,
            "covered_by": sorted({*by_dim.get(cx.dimensions[0], []),
                                  *by_dim.get(cx.dimensions[1], [])}),
        })

    batches: List[Dict[str, Any]] = []
    for th in model.themes:
        seeds = dict(th.seeds or {})
        total = int(seeds.get("count", 0)) + int(seeds.get("explore", 0))
        batches.append({
            "theme": th.key,
            "name": th.label,
            "priority": th.priority,
            "test": th.test,
            "method": th.method,
            "checks": list(th.checks),
            "dimensions": [d.key for d in (th.dims or [])],
            "seeds": seeds,
            "total_runs": total,
        })
        if not th.test:
            notes.append(f"批次 {th.key} 没有 test 名 —— 回归里铺不成一条 test")
        elif not seeds:
            notes.append(f"批次 {th.key}（{th.test}）没有声明 seeds —— "
                         f"回归按默认跑一条，覆盖强度没被声明过")

    # ── §8 需求追溯：把三张表按 requirement 串起来 ──
    #
    # **编号要拆**：一条交叉常同时对应两条需求（`REQ-NPU-002/005` 表示"这两条"）。
    # 不拆的话它自己成一条"需求 REQ-NPU-002/005"，而 REQ-NPU-002 那一行没有
    # 交叉 —— 追溯矩阵正好在**最该串起来的地方**断掉。
    reqs: Dict[str, Dict[str, Any]] = {}

    def _refs(raw: str) -> List[str]:
        """`REQ-NPU-002/005` → `["REQ-NPU-002", "REQ-NPU-005"]`。

        **后半段是省略前缀的写法**（`/005` 是 `/REQ-NPU-005` 的简写），照 `/`
        硬拆会得到一条叫 `005` 的"需求" —— 追溯矩阵上凭空多出一条，而真正的
        `REQ-NPU-005` 那一行仍然没有交叉。所以：**第一段的前缀补回给后面那些
        没有分隔符的段**。
        """
        parts = [x.strip() for x in re.split(r"[/、,，;；]", str(raw or ""))
                 if x.strip()]
        if not parts:
            return []
        m = re.match(r"^(.*[-_])", parts[0])       # 贪心 → 取到最后一个分隔符
        prefix = m.group(1) if m else ""
        return [parts[0]] + [x if re.search(r"[-_]", x) else prefix + x
                             for x in parts[1:]]

    def _slot(req: str) -> Dict[str, Any]:
        return reqs.setdefault(req, {"requirement": req, "coverpoints": [],
                                     "crosses": [], "batches": []})
    for cp in coverpoints:
        for r in _refs(cp["requirement"]):
            _slot(r)["coverpoints"].append(cp["cover_id"] or cp["signal"])
    for cx in crosses:
        for r in _refs(cx["requirement"]):
            _slot(r)["crosses"].append(cx["cover_id"] or cx["name"])
    for b in batches:
        for dim in b["dimensions"]:
            for cp in coverpoints:
                if cp["dimension"] != dim:
                    continue
                for r in _refs(cp["requirement"]):
                    slot = _slot(r)
                    if b["theme"] not in slot["batches"]:
                        slot["batches"].append(b["theme"])

    # 「孤立需求」= 既没有覆盖点、也没有交叉认领它。
    # **只看 coverpoints 是错的**：一条需求由交叉覆盖（而不是某个覆盖点）完全
    # 正当 —— 按前者算会把 X_NPU_* 认领的那几条需求全判成孤立。
    #
    # 现在这份模型里它**不可能命中**（需求只从字段/交叉上"长"出来，没有独立的
    # `requirements:` 声明块）。留着是为了 §9.1 那个措辞不落空：等模型能单独
    # 声明需求时，这里自动开始生效。
    orphan_reqs = [r["requirement"] for r in reqs.values()
                   if not r["coverpoints"] and not r["crosses"]]
    orphan_cps = [cp["signal"] for cp in coverpoints if not cp["requirement"]]
    if orphan_reqs:
        notes.append(f"有需求既没有覆盖点也没有交叉：{'、'.join(sorted(orphan_reqs))} "
                     f"—— 签核要的「无孤立需求」过不了")
    if orphan_cps:
        notes.append(f"有覆盖点没有需求编号：{'、'.join(sorted(orphan_cps))} "
                     f"—— 签核要的「无孤立覆盖点」过不了")

    return {
        "object": model.object,
        "object_cn": model.object_cn,
        "module": cm.module,
        "covergroup": cm.covergroup,
        "sampling": dict(model.sampling or {}),
        "coverpoints": coverpoints,
        "crosses": crosses,
        "batches": batches,
        "traceability": [reqs[k] for k in sorted(reqs)],
        "summary": {
            "coverpoint_count": len(coverpoints),
            "bin_count": sum(c["bin_count"] for c in coverpoints),
            "cross_count": len(crosses),
            "cross_bin_count": sum(c["bin_count"] for c in crosses),
            "illegal_bin_count": (sum(len(c["illegal_bins"]) for c in coverpoints)
                                  + sum(len(c["illegal_bins"]) for c in crosses)),
            "batch_count": len(batches),
            "requirement_count": len(reqs),
            "total_runs": sum(b["total_runs"] for b in batches),
        },
        "notes": list(dict.fromkeys(notes + list(cm.notes))),
    }
