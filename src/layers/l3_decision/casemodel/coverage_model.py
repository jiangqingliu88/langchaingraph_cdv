"""覆盖率模型 —— 覆盖点/仓/交叉的数据形状，以及 case 模型 → covergroup 模型。

从 `casemodel_tools/coverage.py` 拆出；`coverage` 继续 re-export 这些名字。
**不渲染、不解析**：这里只有数据形状与构建规则（方法学见 `coverage.py` 模块头）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional

from .domain import CaseModel, Field, token_of

CROSSABLE_LEVELS = ("required", "optional")


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
    #: **忽略仓**：采样到也不计入分母（工具级排除，不是人工 waiver）。
    ignore: bool = False
    #: **转移仓**：`(a => b)` —— 状态/取值迁移的覆盖，不是单值。
    transitions: List[tuple] = _field(default_factory=list)
    #: UVM 语义：仓/覆盖点的权重与最少命中次数（1 = 默认）。
    weight: int = 1
    at_least: int = 1

    def literal(self) -> str:
        """`bins` 右边那对花括号里的东西 —— **唯一进 SV 的部分**。"""
        if self.lo is not None:
            return f"[{self.lo}:{'$' if self.hi is None else self.hi}]"
        if self.values:
            return ",".join(str(v) for v in self.values)
        return str(self.value if self.value is not None else 0)

    def render_rhs(self) -> str:
        """完整的仓右值：普通仓带花括号，转移仓是 `(a => b)`。"""
        if self.transitions:
            return ", ".join(f"({a} => {b})" for a, b in self.transitions)
        return "{" + self.literal() + "}"

    def as_dict(self) -> Dict[str, Any]:
        out = {"name": self.name, "token": self.token, "boundary": self.boundary,
               "illegal": self.illegal, "ignore": self.ignore,
               "weight": self.weight, "at_least": self.at_least,
               "literal": self.literal(), "rhs": self.render_rhs()}
        if self.transitions:
            out["transitions"] = [list(t) for t in self.transitions]
        elif self.lo is not None:
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
    #: **SV 里那个 coverpoint 的名字**（空 → 按 `cp_<signal>` 推）。
    #:
    #: 为什么要有独立的一份：**交叉引用的是 coverpoint 名，不是信号名**。
    #: 独立覆盖率模型（`parse_coverage_model`）里作者写
    #: `name: cp_instr_type` + `signal: instr_type`，交叉写
    #: `cross: [cp_dep_type, cp_issue_decision]` —— 引用的是**名字**。
    #: 靠"名字恰好等于 `cp_<signal>`"来对齐是巧合，不是契约。
    cp_name: str = ""
    bins: List[CoverBin] = _field(default_factory=list)
    illegal_bins: List[CoverBin] = _field(default_factory=list)
    #: 覆盖点级 UVM 选项（0 = 不写，沿用 covergroup 默认）。
    weight: int = 0
    at_least: int = 0

    @property
    def sv_name(self) -> str:
        """SV 里那个 coverpoint 名（作者给了就用作者的）。"""
        return self.cp_name or f"cp_{self.signal}"

    def as_dict(self) -> Dict[str, Any]:
        return {"signal": self.signal, "field": self.field,
                "dimension": self.dimension, "type": self.type,
                "cp_name": self.sv_name,
                "cover_id": self.cover_id, "requirement": self.requirement,
                "source": self.source, "width": self.width, "expr": self.expr,
                "weight": self.weight, "at_least": self.at_least,
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
    ignore: bool = False
    weight: int = 1
    at_least: int = 1

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "when": dict(self.when),
                "illegal": self.illegal, "ignore": self.ignore,
                "weight": self.weight, "at_least": self.at_least}


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
    #: **参与交叉的 coverpoint 名**（空 → 按 `cp_<signal>` 推）。见 `CoverPoint.cp_name`。
    cp_refs: List[str] = _field(default_factory=list)
    #: **关联到 case 模型的 `cross_matrix` 键**（`指令类型×数据类型`）——
    #: 这是三层模型之间那条"组合关系对组合关系"的引用（`run_associate` 用它查 dangling）。
    matrix_ref: str = ""

    @property
    def refs(self) -> List[str]:
        """SV 里 `cross` 那句引用的 coverpoint 名（作者给了就用作者的）。"""
        return list(self.cp_refs) or [f"cp_{s}" for s in self.signals]

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "signals": list(self.signals),
                "cp_refs": self.refs, "matrix_ref": self.matrix_ref,
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
    #: **关联到 case 模型的 L1 对象**（`object_ref: NpuScheduler`）——
    #: 独立覆盖率模型里显式声明它属于哪个对象。
    object_ref: str = ""
    coverpoints: List[CoverPoint] = _field(default_factory=list)
    crosses: List[CrossPoint] = _field(default_factory=list)
    #: covergroup 级 UVM 选项（per_instance / weight / at_least / auto_bin_max）。
    options: Dict[str, Any] = _field(default_factory=dict)
    notes: List[str] = _field(default_factory=list)
    #: **硬错** —— 关联断了、取值投影不了这类。有它就**不许渲染 SV**。
    #:
    #: 为什么单独一份而不是混进 `notes`：解析"能读出个东西"和"这东西是对的"是两件事。
    #: 取值解析不了时给个 0 让 bin 照生成，plot 出来的覆盖率是**错的数**——
    #: 那比不生成更坏（一个永远不命中的 bin 至少一眼看得出来）。
    errors: List[str] = _field(default_factory=list)

    @property
    def renderable(self) -> bool:
        """能不能拿它渲染 SV —— 有硬错就不行。"""
        return bool(self.coverpoints) and not self.errors

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
            "options": dict(self.options),
            "coverpoint_count": len(self.coverpoints),
            "bin_count": self.bin_count,
            "cross_count": len(self.crosses),
            "stimulus_coverpoint_count": len(self.by_source("stimulus")),
            "dut_coverpoint_count": len(self.by_source("dut")),
            "notes": list(self.notes),
        }


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


def coverage_model(model: CaseModel, module_name: str = "dut") -> CoverageModel:
    """`CaseModel` → `CoverageModel`（覆盖点的声明）。

    调用方应当传 **`resolve()` 过**的模型：`cross_pair.dim_a/dim_b` 与联动的取值
    都是 `resolve()` 回填的，没解析过就会少 cross、少 bin（且是**静默**少）。
    这里对没解析的情况记账（见 `notes`）。
    """
    module = sv_ident(module_name or model.object or "dut", "dut")
    cm = CoverageModel(module=module, covergroup=f"cg_{module}",
                       options=_sampling_options(model.sampling or {}))

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


#: covergroup 级 UVM 选项（与 `sampling:` 同名读取）。
_SAMPLING_OPTIONS = ("per_instance", "weight", "at_least", "auto_bin_max",
                     "strobe")


def _sampling_options(sampling: Dict[str, Any]) -> Dict[str, Any]:
    return {k: sampling[k] for k in _SAMPLING_OPTIONS
            if sampling.get(k) is not None}


def _uniform_opt(bins: List[CoverBin], attr: str, notes: List[str],
                 where: str) -> int:
    """仓级 `weight`/`at_least` → 覆盖点级选项（**UVM 是覆盖点/组级**）。

    所有有效仓取同一个非默认值才提升；不一致就记账并用默认 —— 不编一个
    "看起来像逐仓"的语义（SV 的 bins 声明没有这种语法）。
    """
    vals = {int(getattr(b, attr) or 0) for b in bins
            if not b.illegal and not b.ignore}
    vals = {v for v in vals if v > 1}
    if not vals:
        return 0
    if len(vals) == 1:
        return next(iter(vals))
    notes.append(f"{where}：每个仓的 {attr} 不一致 {sorted(vals)} —— "
                 f"按覆盖点默认处理（{attr} 是覆盖点级选项，不是仓级）")
    return 0


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

        bin_ = CoverBin(name=name, illegal=illegal,
                        ignore=bool(item.get("ignore")),
                        weight=_as_int(item.get("weight"))
                        if item.get("weight") is not None else 1,
                        at_least=_as_int(item.get("at_least"))
                        if item.get("at_least") is not None else 1)
        # 转移仓：`(a => b)`。与单值/区间互斥，先判。
        transitions = _transitions(item)
        if transitions:
            bin_.transitions = transitions
            bin_.token = " => ".join(f"{a}:{b}" for a, b in transitions)
            out.append(bin_)
            continue
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
            notes.append(f"{where}：仓 {name} 既没有 range/from/at/transitions "
                         f"也没有 values —— 跳过（没法生成一个空的 bins）")
            continue
        out.append(bin_)
    return out


def _transitions(item: Dict[str, Any]) -> List[tuple]:
    """`transitions:` / `transition:` → `[(from, to), …]`（转移仓）。"""
    raw = item.get("transitions")
    if raw is None:
        raw = item.get("transition")
    if raw is None:
        return []
    out: List[tuple] = []
    for entry in (raw if isinstance(raw, list) else [raw]):
        if isinstance(entry, dict):
            a, b = entry.get("from"), entry.get("to")
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            a, b = entry[0], entry[1]
        else:
            continue
        if a is not None and b is not None:
            out.append((_as_int(a), _as_int(b)))
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
                      width=width, expr=fld.sample_expr,
                      weight=_uniform_opt(bins, "weight", notes, where),
                      at_least=_uniform_opt(bins, "at_least", notes, where))


def _derive_width_from_bins(bins: List[CoverBin]) -> int:
    """没有 case 字段时，从 bin 内容推位宽（取出现过的最大数需要几位）。"""
    hi = 0
    for b in bins:
        for v in ([b.value] if b.value is not None else []) + list(b.values) +                  ([b.hi] if b.hi is not None else []):
            if v is not None:
                hi = max(hi, int(v))
    return max(1, hi.bit_length())


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
            cover_id=pair.cover_id, requirement=pair.requirement,
            # **回填 `cross_matrix` 键**：`<a>×<b>` 就是 case 模型里那个键
            # （`D_type×D_unit`）—— 边 ② 靠它对账。**原来这里没传，恒为空串**：
            # 派生出来的模型每条交叉的 `matrix_ref` 都是 `''`，于是
            # `associate` 边 ② 对所有 case 矩阵键都报"没有任何交叉引用它"
            #（实测 npu_sched：7 条全报），而真相是"这一侧根本没填"。
            # 手写覆盖率模型的作者会自己填这一项；派生路径得替作者填上。
            matrix_ref=f"{pair.a}×{pair.b}"))
    _attach_group_crosses(model, cm, by_dim)


def _attach_group_crosses(model: CaseModel, cm: CoverageModel,
                          by_dim: Dict[str, CoverPoint]) -> None:
    """`cross_groups` → N 元交叉（**跨组 cross 的落地实现**）。

    `cross_matrix` 只表达"两两是否可组合"；`cross_groups` 是"这一组维度必须
    一起组合"（`X_ISSUE_DEP_PATH` 这种 N 元组合）。SV 的 `cross` 支持多个
    coverpoint，所以直接生成 `cross cp_a, cp_b, cp_c;`。

    去重：如果这组维度已经由 `cross_matrix` 的某条两两交叉覆盖，就跳过（组
    级别的交叉会在 ucdb 里多一份重复计量）。每维只取**第一个覆盖点**；一维多
    字段时记账说明，不静默丢。
    """
    existing = {tuple(sorted(cx.dimensions)) for cx in cm.crosses}
    for grp in model.cross_groups:
        if grp.level == "forbidden" or grp.level not in CROSSABLE_LEVELS:
            cm.notes.append(
                f"cross_group {grp.key} 的级别 {grp.level!r} 不生成交叉")
            continue
        dims = list(grp.dims) or [model.dimension(ref) for ref in grp.dimensions]
        dims = [d for d in dims if d is not None]
        if len(dims) < 2:
            cm.notes.append(f"cross_group {grp.key} 解出的维度不足 2 个 —— 跳过")
            continue
        key = tuple(sorted(d.key for d in dims))
        if key in existing:
            continue
        cps = [by_dim.get(d.key) for d in dims]
        missing = [d.key for d, cp in zip(dims, cps) if cp is None]
        if missing:
            cm.notes.append(
                f"cross_group {grp.key} 的维度 {'、'.join(missing)} 没有覆盖点 —— 跳过")
            continue
        sources = {cp.source for cp in cps}
        if len(sources) > 1:
            cm.notes.append(
                f"cross_group {grp.key} 的维度采样来源不同"
                f"（{'、'.join(sorted(sources))}）—— 跳过：cross 要求同作用域")
            continue
        for d in dims:
            if len(d.fields) > 1:
                cm.notes.append(
                    f"cross_group {grp.key}：维度 {d.key} 有 {len(d.fields)} 个字段，"
                    f"只交叉第一个（{d.fields[0].name}）")
        cm.crosses.append(CrossPoint(
            name=f"cx_grp_{sv_ident(grp.key, 'grp')}",
            signals=[cp.signal for cp in cps], level=grp.level,
            dimensions=[cp.dimension for cp in cps], bins=[],
            source=cps[0].source, cover_id=grp.id, matrix_ref=grp.key))
        existing.add(key)


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
        # 交叉仓也有 ignore / weight / at_least 语义（与普通仓同口径）
        ignore = bool(item.get("ignore"))
        weight = _as_int(item.get("weight")) if item.get("weight") is not None else 1
        at_least = (_as_int(item.get("at_least"))
                    if item.get("at_least") is not None else 1)
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
                                illegal=bool(item.get("illegal")),
                                ignore=ignore, weight=weight,
                                at_least=at_least))
    return out


def _match_bin(cp: CoverPoint, want: Any) -> Optional[str]:
    """`want` → 这个覆盖点里实际存在的仓名。**bin 名与取值 token 都认。**"""
    w = str(want).strip()
    for b in cp.bins:
        if b.name == w or b.token == w:
            return b.name
    return None
