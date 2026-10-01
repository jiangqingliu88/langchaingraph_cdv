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
    cover_bins: List[str] = _field(default_factory=list)
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

    def bins_for(self, token: str) -> List[str]:
        """取值 → 覆盖仓。

        cover_bins 与取值点等长时按下标对齐（推荐写法）；否则整体挂上 ——
        宁可多报几个仓，也不要因为长度不齐就静默丢掉映射。
        """
        if not self.cover_bins:
            return []
        points = self.value_points()
        if len(self.cover_bins) == len(points):
            for p, b in zip(points, self.cover_bins):
                if p.token == token:
                    return [b]
        return list(self.cover_bins)


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
        cover_bins=[str(c) for c in as_list(item.get("cover_bins"))],
        unit=str(item.get("unit") or ""),
        dim_key=dim_key,
    )
