"""取值覆盖的数据类型与构造。

单独成模块，是因为三条路径都要用同一套覆盖结构 ——
「模型生成的 case」、「真实 case 列表」、以及将来的「仿真覆盖率数据」。
只有这样报告和 GUI 才能把它们并排放在一起比较。

FieldCoverage / DimensionCoverage 本身不含判定逻辑：
「怎么算命中」由调用方提供 hits 字典，
「命中多少才算够」由 rules/coverage.py 决定。
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from ..domain import FIELD_TYPE_NAMES, Dimension


@dataclass
class FieldCoverage:
    dimension: str = ""
    dimension_name: str = ""
    field: str = ""
    field_type: str = ""
    tokens: List[str] = _field(default_factory=list)
    hit: List[str] = _field(default_factory=list)
    derived: bool = False            # 联动派生：取值跟随目标字段

    @property
    def missing(self) -> List[str]:
        hit = set(self.hit)
        return [t for t in self.tokens if t not in hit]

    @property
    def total(self) -> int:
        return len(self.tokens)

    @property
    def hit_count(self) -> int:
        return len(self.hit)

    @property
    def ratio(self) -> float:
        return self.hit_count / self.total if self.total else 1.0

    @property
    def type_name(self) -> str:
        return FIELD_TYPE_NAMES.get(self.field_type, self.field_type)

    @property
    def full(self) -> bool:
        return self.hit_count >= self.total


@dataclass
class DimensionCoverage:
    key: str = ""
    name: str = ""
    fields: List[FieldCoverage] = _field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(f.total for f in self.fields)

    @property
    def hit_count(self) -> int:
        return sum(f.hit_count for f in self.fields)

    @property
    def ratio(self) -> float:
        return self.hit_count / self.total if self.total else 1.0

    @property
    def missing(self) -> List[Tuple[str, List[str]]]:
        return [(f.field, f.missing) for f in self.fields if f.missing]


def build_dimension_coverage(
    dimensions: Sequence[Dimension],
    hits: Dict[str, Set[str]],
) -> Tuple[List[DimensionCoverage], List[FieldCoverage]]:
    """按字段名查命中集合 → 逐维度/逐字段的覆盖结构。

    以字段名为键（与文档十六节的属性表一致）。字段名重复时命中会串味，
    这件事由 completeness 的 duplicate_field_name / coverage_ambiguous_field 报出来。
    """
    dim_cov: List[DimensionCoverage] = []
    all_cov: List[FieldCoverage] = []
    for dim in dimensions:
        dcov = DimensionCoverage(key=dim.key, name=dim.label)
        for fld in dim.fields:
            tokens = fld.cover_tokens()
            hit = [t for t in tokens if t in hits.get(fld.name, set())]
            fc = FieldCoverage(
                dimension=dim.key, dimension_name=dim.label, field=fld.name,
                field_type=fld.type, tokens=tokens, hit=hit,
                derived=fld.is_linkage and bool(fld.linked_to))
            dcov.fields.append(fc)
            all_cov.append(fc)
        dim_cov.append(dcov)
    return dim_cov, all_cov


def hits_from_cases(cases: Iterable[object]) -> Dict[str, Set[str]]:
    """case 属性表 → {字段名: 命中取值集合}。

    只认 `.fields` 这个属性 —— 所以生成的 CaseAttribute 与外部读进来的
    ExternalCase 都能直接喂进来，覆盖统计不必写两遍。
    """
    hits: Dict[str, Set[str]] = {}
    for case in cases:
        for name, token in (getattr(case, "fields", None) or {}).items():
            hits.setdefault(name, set()).add(token)
    return hits


def overall_ratio(dim_cov: Iterable[DimensionCoverage]) -> float:
    total = sum(d.total for d in dim_cov)
    hit = sum(d.hit_count for d in dim_cov)
    return hit / total if total else 1.0


def missing_pairs(dim_cov: Iterable[DimensionCoverage]) -> List[Tuple[str, str, str]]:
    """→ [(维度名, 字段名, 缺失取值)]，按维度/字段顺序展开。"""
    out: List[Tuple[str, str, str]] = []
    for d in dim_cov:
        for f in d.fields:
            for token in f.missing:
                out.append((d.name, f.field, token))
    return out
