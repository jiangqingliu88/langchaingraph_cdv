"""L4 字段 —— 唯一承载取值的层级。

设计模式：**Strategy**。文档十三节把字段类型化成五种（枚举/范围/集合/加权/联动），
它们唯一的差别就是「取值点从哪来」，也就是「覆盖分母是什么」。
所以抽成一个策略族，由 `Field.type` 选一个；新增字段类型 = 新增一个子类 +
在 FIELD_TYPE_REGISTRY 登记，不用动任何调用方。

维度只负责归类，字段才负责取值 —— 这条纪律体现在类型里：
Dimension 持有 List[Field]，Field 持有 List[ValuePoint]，再往下没有层了。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional

from .vocab import FIELD_TYPE_NAMES, num, token_of, value_of, weight_of


@dataclass
class ValuePoint:
    """字段的一个候选取值点。

    同时服务于两件事：生成时从这里挑取值，算覆盖率时它是分母的一个刻度。
    """
    token: str
    raw: Any = None
    weight: Optional[float] = None
    boundary: bool = False          # 边界取值 —— SPCL 专项只推边界

    @property
    def is_edge(self) -> bool:
        return self.boundary

    @property
    def label(self) -> str:
        return f"{self.token} (w={self.weight:g})" if self.weight is not None else self.token


# ════════════════════════════════════════════════════════════
# 类型策略
# ════════════════════════════════════════════════════════════

class FieldType(ABC):
    """字段类型策略。子类只回答「这个字段有哪些取值点」。"""

    key: str = ""
    name: str = ""

    @abstractmethod
    def value_points(self, fld: "Field") -> List[ValuePoint]:
        ...

    def cover_tokens(self, fld: "Field") -> List[str]:
        """覆盖缺口分析的分母。默认就是全部取值点的 token。"""
        return [p.token for p in self.value_points(fld)]


class EnumField(FieldType):
    """枚举型：值表平铺，互相无关系。"""
    key = "enum"
    name = "枚举型"

    def value_points(self, fld: "Field") -> List[ValuePoint]:
        declared = set(fld.boundary or ())
        return [ValuePoint(token=token_of(v), raw=value_of(v),
                           weight=weight_of(v),
                           boundary=token_of(v) in declared if declared else False)
                for v in fld.values]


class SetField(EnumField):
    """集合型：当前与枚举型共用同一套取值点算法。

    文档把二者分开，是因为集合型的本意是「从一组取值里选子集」（覆盖是按
    子集命中算的），而枚举型是「每次都取其中一个」。生成侧的行为此时完全一致，
    所以这里先继承枚举的实现，等真需要子集语义时只覆盖本类即可 —— 调用方不用改。
    """
    key = "set"
    name = "集合型"


class WeightedField(EnumField):
    """加权型：取值点带权重，RND 按权重分布采样。

    权重只影响「挑哪个」的概率，不影响覆盖分母 —— 加权型也要求每个取值都被覆盖到。
    """
    key = "weighted"
    name = "加权型"


class RangeField(FieldType):
    """范围型：取值连续，无法枚举。

    覆盖点用 `boundary` 显式声明；没声明就退化成 min/max 两个端点。
    边界分析也只认 boundary，所以声明得越细，SPCL 专项推得越准。
    """
    key = "range"
    name = "范围型"

    def value_points(self, fld: "Field") -> List[ValuePoint]:
        if fld.boundary:
            return [ValuePoint(token=str(b), raw=b, boundary=True)
                    for b in fld.boundary]
        pts: List[ValuePoint] = []
        if fld.min is not None:
            pts.append(ValuePoint(token=token_of(fld.min), raw=fld.min, boundary=True))
        if fld.max is not None:
            pts.append(ValuePoint(token=token_of(fld.max), raw=fld.max, boundary=True))
        return pts


class LinkageField(FieldType):
    """联动型：自己不独立取值，跟随 linked_to 指向的字段。

    取值表由 CaseModel.resolve() 从目标字段回填（见 domain/model.py），
    所以这里只负责把回填来的取值转成取值点。目标不在同一组合里时，
    它退化成一根普通的轴 —— 生成侧由 generation 决定，与本策略无关。
    """
    key = "linkage"
    name = "联动型"

    def value_points(self, fld: "Field") -> List[ValuePoint]:
        return [ValuePoint(token=token_of(v), raw=value_of(v)) for v in fld.values]


FIELD_TYPE_REGISTRY: Dict[str, FieldType] = {
    t.key: t for t in (EnumField(), SetField(), WeightedField(), RangeField(),
                       LinkageField())
}


def field_type(key: str) -> FieldType:
    """查不到就退化为枚举型 —— 与 schema 层的「未知 type 直接报错」互补：
    schema 挡住非法输入，这里保证即便被绕过也不会崩。
    """
    return FIELD_TYPE_REGISTRY.get(key) or FIELD_TYPE_REGISTRY["enum"]


# ════════════════════════════════════════════════════════════
# 字段
# ════════════════════════════════════════════════════════════

@dataclass
class Field:
    """L4 字段。"""
    name: str
    type: str = "enum"
    description: str = ""
    values: List[Any] = _field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    linked_to: str = ""
    boundary: List[str] = _field(default_factory=list)
    #: **覆盖仓**。两种写法（可混用）：
    #:
    #:   · 字符串 —— 给**第 i 个取值点**命名（下标对齐）。`["mac","vector"]`
    #:     配上 `values: [0,1]` 就是"取值 0 叫 mac、取值 1 叫 vector"。
    #:   · 对象 —— **显式定义一个仓**，内容自己做主：
    #:       `{name: low,  range: [1, 7]}`      → `bins low = {[1:7]};`
    #:       `{name: full, at: 32}`             → `bins full = {32};`
    #:       `{name: set,  values: [0, 7, 8]}`  → `bins set = {0,7,8};`
    #:
    #: 为什么需要对象形式：**仓不必是取值点**。`queue_level` 的 0-32 要分
    #: `empty/low/mid/high/near_full/full` 六档 —— 那是**值域的一个划分**，
    #: 不是"取了哪几个点"，用取值点表达不出来。
    cover_bins: List[Any] = _field(default_factory=list)
    #: **非法仓** —— 命中即报错（SV 的 `illegal_bins`）。形状同 `cover_bins` 的
    #: 对象形式。`{name: illegal_over, from: 33}` → `illegal_bins illegal_over = {[33:$]};`
    #:
    #: 这是"约束与覆盖点脱节"那条坑的解药：与其指望激励永不产生非法组合，
    #: 不如把它**声明出来**，一旦真出现，仿真当场报，而不是等覆盖率对不上再回查。
    cover_illegal: List[Any] = _field(default_factory=list)
    #: **覆盖点编号** —— 人给的稳定标识（`CP_NPU_QUEUE_001`）。
    #:
    #: 生成器派生的名字是 `cp_<信号名>`，那是给 SV 用的；而"覆盖点总览""需求
    #: 追溯矩阵"里引用的编号是**文档里的那个**。两者都要有：一个给编译器、
    #: 一个给人对账。不填就是没有编号（不编一个出来）。
    cover_id: str = ""
    #: **需求编号** —— `REQ-NPU-001`。签核要回答"每条需求被谁验了"，
    #: 这条链就是 `需求 → 覆盖点 → 用例 → 实测命中`。
    requirement: str = ""
    #: **这个信号从哪采** —— 决定它走哪条采样通道。两条通道的可见性完全不同：
    #:
    #:   · `stimulus`（默认）—— **事务字段**。monitor 采到的事务对象上的字段，
    #:     由 `env_cov.sv.j2` 的 `cg_<agent>` 采（monitor 每笔事务触发 `sample()`）。
    #:     **只看得到激励侧**：DUT 内部的队列水位、依赖类型、输出端口，一个都采不到。
    #:   · `dut` —— **DUT 里按名字可见的信号**：输入端口、输出端口、以及**内部寄存器**。
    #:     对一个 `bind` 进 DUT 的探针模块来说，这三者没有区别 —— 端口连接表达式
    #:     是在**目标模块作用域**里求值的（实测）。
    #:
    #: 默认给 `stimulus` 是**为了不动已经跑通的那条路**（apb_uart 的属性测试点走
    #: env_cov 通道）。一个计划文档里大量采内部状态的模型（NPU 调度器就是）
    #: 应当逐字段写 `sample: dut`。
    sample: str = "stimulus"
    #: 采样信号的**位宽**（`dut` 通道要它来声明探针端口）。
    #:
    #: 不给就按类型推导：`range` 取容纳 `max` 的位数，`enum` 取容纳取值下标的位数。
    #: 推出来的可能与 DUT 实际宽度不同（枚举 4 个取值推 2 位，而端口是 3 位）——
    #: 值域仍在推出来的宽度里，所以**采到的值是对的**，但会有截断告警。
    #: 想要零告警就显式写。
    width: Optional[int] = None
    #: **采样表达式** —— 不写就采同名信号；写了就采这个表达式（`dut` 通道专用）。
    #:
    #: 给**派生信号**用：`instr_seq`（相邻两条 opcode 的组合）既不是端口也不是
    #: 寄存器，得有人算出来。要么 DUT 自己暴露它（那就同名，不用写这个），
    #: 要么在探针的作用域里能写成表达式。
    sample_expr: str = ""
    unit: str = ""
    dim_key: str = ""               # 所属维度 key，由 Dimension 构建时回填

    # ── 展示 ──

    @property
    def qualified(self) -> str:
        return f"{self.dim_key}.{self.name}" if self.dim_key else self.name

    @property
    def type_name(self) -> str:
        return FIELD_TYPE_NAMES.get(self.type, self.type)

    @property
    def is_linkage(self) -> bool:
        return self.type == "linkage"

    # ── 取值：全部委托给类型策略 ──

    def value_points(self) -> List[ValuePoint]:
        return field_type(self.type).value_points(self)

    def cover_tokens(self) -> List[str]:
        return field_type(self.type).cover_tokens(self)

    def value_labels(self) -> List[str]:
        return [p.label for p in self.value_points()]

    def named_bins(self) -> List[str]:
        """`cover_bins` 里**字符串**那些 —— 它们才对取值点做下标对齐。

        对象条目是"显式定义一个仓"，与取值点没有一一对应关系，掺进对齐里
        会把下标错位（第 2 个取值点拿到第 3 个仓的名字）。所以先滤出来。
        """
        return [b for b in self.cover_bins if isinstance(b, str)]

    def explicit_bins(self) -> List[Any]:
        """`cover_bins` 里**对象**那些 —— 它们自己定义仓，不靠取值点。"""
        return [b for b in self.cover_bins if isinstance(b, dict)]

    def bins_for(self, token: str) -> List[str]:
        """取值 → 覆盖仓（**只认字符串形式的名字**）。

        名字与取值点等长时按下标对齐（推荐写法）；否则整体挂上 ——
        宁可多报几个仓，也不要因为长度不齐就静默丢掉映射。
        """
        named = self.named_bins()
        if not named:
            return []
        points = self.value_points()
        if len(named) == len(points):
            for p, b in zip(points, named):
                if p.token == token:
                    return [b]
        return list(named)


def build_field(item: Any, dim_key: str) -> Field:
    """YAML 的一条 field → Field。非 mapping 的条目按「只有名字」处理。"""
    from .vocab import as_list, FIELD_TYPES

    if not isinstance(item, dict):
        return Field(name=str(item), dim_key=dim_key)

    ftype = str(item.get("type") or "enum").strip().lower()
    if ftype not in FIELD_TYPES:
        ftype = "enum"
    return Field(
        name=str(item.get("name") or "").strip(),
        type=ftype,
        description=str(item.get("description") or ""),
        values=list(as_list(item.get("values"))),
        min=num(item.get("min")),
        max=num(item.get("max")),
        step=num(item.get("step")),
        linked_to=str(item.get("linked_to") or "").strip(),
        boundary=[str(b) for b in as_list(item.get("boundary"))],
        # 字符串原样留、**对象原样留** —— 后者是显式仓定义，`str()` 一下就成了
        # `"{'name': 'low', ...}"` 这种废字符串，静默丢掉一个仓
        cover_bins=[c if isinstance(c, dict) else str(c)
                    for c in as_list(item.get("cover_bins"))],
        cover_illegal=list(as_list(item.get("cover_illegal"))),
        cover_id=str(item.get("cover_id") or "").strip(),
        requirement=str(item.get("requirement") or "").strip(),
        sample=str(item.get("sample") or "stimulus").strip().lower(),
        width=(int(item["width"]) if str(item.get("width") or "").strip().isdigit()
               else None),
        sample_expr=str(item.get("sample_expr") or "").strip(),
        unit=str(item.get("unit") or ""),
        dim_key=dim_key,
    )
