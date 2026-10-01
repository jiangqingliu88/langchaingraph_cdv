"""L3 维度，以及维度之间的组合关系（交叉对 / 交叉组）。

维度只归类、不承载取值 —— 取值全在 fields 里（文档六节）。维度之间的关系
表达成两张东西：
  · `relation`   维度内部（或跨维度）的字段两两关系：并列 / 联动 / 互斥
  · `CrossPair`  两个维度之间要不要一起组合：★ 必需 / ✓ 可选 / ✗ 禁止
  · `CrossGroup` 一组必须一起组合的维度（矩阵里每个 ★ 对应一个组）

注意三者都不是「专题」。专题是横切在功能组织树上的验证关注点，
层级在维度之上（见 domain/themes.py）；交叉矩阵只描述维度之间怎么配。
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional

from .fields import Field, build_field
from .vocab import (CROSS_LEVEL_MARKS, CROSS_LEVEL_NAMES, METHOD_ALIASES,
                    RELATION_ALIASES, as_list, canon)


@dataclass
class Dimension:
    """L3 维度 —— 一组语义相关字段的集合。"""
    key: str
    id: str = ""
    name: str = ""
    description: str = ""
    sub_objects: List[str] = _field(default_factory=list)   # 限定的组织树节点
    relation: Dict[str, str] = _field(default_factory=dict)  # 另一字段名 → 关系
    fields: List[Field] = _field(default_factory=list)

    @property
    def field_names(self) -> List[str]:
        return [f.name for f in self.fields]

    @property
    def label(self) -> str:
        return self.name or self.id or self.key

    @property
    def value_point_count(self) -> int:
        return sum(len(f.cover_tokens()) for f in self.fields)

    def matches(self, ref: str) -> bool:
        r = (ref or "").strip()
        if r in (self.id, self.name, self.key):
            return True
        low = r.lower()
        return low in (self.id.lower(), self.name.lower(), self.key.lower())

    def contains(self, ref: str) -> bool:
        """松匹配：文档的矩阵表头常用简称（长度 ↔ 指令长度）。"""
        r = (ref or "").strip()
        if not r:
            return False
        return any(c and (r in c or c in r) for c in (self.id, self.name, self.key))


@dataclass
class CrossPair:
    """两个维度的交叉关系（矩阵的一个格子）。"""
    a: str
    b: str
    level: str = "optional"
    reason: str = ""
    source: str = "declared"        # declared | group
    dim_a: Optional[Dimension] = _field(default=None, repr=False, compare=False)
    dim_b: Optional[Dimension] = _field(default=None, repr=False, compare=False)

    @property
    def resolved(self) -> bool:
        return self.dim_a is not None and self.dim_b is not None

    @property
    def level_name(self) -> str:
        return CROSS_LEVEL_NAMES.get(self.level, self.level)

    @property
    def mark(self) -> str:
        return CROSS_LEVEL_MARKS.get(self.level, "?")


@dataclass
class CrossGroup:
    """交叉组 —— 一组必须一起组合的维度。"""
    id: str
    name: str = ""
    dimensions: List[str] = _field(default_factory=list)    # 原始引用
    level: str = "required"
    method: str = ""
    sub_objects: List[str] = _field(default_factory=list)
    checks: List[str] = _field(default_factory=list)
    expected_result: str = ""
    description: str = ""
    dims: List[Dimension] = _field(default_factory=list)    # resolve 后
    unresolved: List[str] = _field(default_factory=list)
    source: str = "declared"        # declared | derived

    @property
    def key(self) -> str:
        return self.id or self.name

    @property
    def label(self) -> str:
        return self.name or self.id or "×".join(self.dimensions)

    def dimension_keys(self) -> List[str]:
        return [d.key for d in self.dims] or list(self.dimensions)


# ════════════════════════════════════════════════════════════
# 构建
# ════════════════════════════════════════════════════════════

def build_dimension(item: Any) -> Optional[Dimension]:
    if not isinstance(item, dict):
        return None
    dim_id = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    key = dim_id or name
    if not key:
        return None

    relation: Dict[str, str] = {}
    for ref, kind in (item.get("relation") or {}).items():
        level = canon(str(kind), RELATION_ALIASES)
        if level:
            relation[str(ref)] = level

    return Dimension(
        key=key, id=dim_id, name=name,
        description=str(item.get("description") or ""),
        sub_objects=[str(s) for s in as_list(item.get("sub_objects"))],
        relation=relation,
        fields=[build_field(f, key) for f in as_list(item.get("fields"))],
    )


def build_cross_pair(key: str, level_raw: Any) -> Optional[CrossPair]:
    from .vocab import CROSS_LEVEL_ALIASES, split_cross_key
    split = split_cross_key(str(key))
    if not split:
        return None
    level = canon(str(level_raw), CROSS_LEVEL_ALIASES) or "optional"
    return CrossPair(a=split[0], b=split[1], level=level, source="declared")


def build_cross_group(item: Any, index: int) -> Optional[CrossGroup]:
    from .vocab import CHECK_ALIASES, CROSS_LEVEL_ALIASES
    if not isinstance(item, dict):
        return None
    return CrossGroup(
        id=str(item.get("id") or f"XG-{index:02d}"),
        name=str(item.get("name") or ""),
        dimensions=[str(d) for d in as_list(item.get("dimensions"))],
        level=canon(str(item.get("level")), CROSS_LEVEL_ALIASES) or "required",
        method=canon(str(item.get("method") or ""), METHOD_ALIASES) or "",
        sub_objects=[str(s) for s in as_list(item.get("sub_objects"))],
        checks=[c for c in (canon(str(x), CHECK_ALIASES)
                            for x in as_list(item.get("checks"))) if c],
        expected_result=str(item.get("expected_result") or ""),
        description=str(item.get("description") or ""),
    )
