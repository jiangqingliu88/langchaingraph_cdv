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
    #: **显式交叉仓**（可选）：`[{name, when: {维度: 仓名}}]`。
    #:
    #: 不给就是**全交叉**（`cross cp_a, cp_b;`，两边的仓两两相乘）；给了就只出
    #: 列出来的那几个（`bins x = binsof(cp_a.ba) && binsof(cp_b.bb);`）。
    #:
    #: 为什么需要它：全交叉的仓数按乘积涨 —— 4×4 就是 16 个，而关心的往往只有
    #: 四五个。更糟的是**非法组合**：`mac` 指令发到 `dma` 单元这种，全交叉会
    #: 给它一个正常的仓，等于在说"这是个合法状态"。见 `illegal`。
    bins: List[Any] = _field(default_factory=list)
    #: **非法交叉仓** —— 命中即报错。形状同 `bins`。
    illegal: List[Any] = _field(default_factory=list)
    #: **交叉编号 / 需求编号** —— 追溯矩阵的另一头（与 `Field.cover_id` 对称）。
    #: 生成器派生的名字是 `cx_<a>_<b>`（给 SV），文档里引用的是
    #: `X_NPU_TYPE_UNIT_001`。两者都要有，不能拿一个当另一个。
    cover_id: str = ""
    requirement: str = ""
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
    """`cross_matrix` 的一个格子 → `CrossPair`。

    值有两种写法：

      · **字符串** —— 只声明级别：`指令长度×反压模式: required`
      · **对象** —— 连仓一起声明：
        ```yaml
        指令类型×执行单元:
          level: required
          bins:
            - {name: mac_to_mac, when: {指令类型: mac, 执行单元: mac}}
          illegal:
            - {name: mac_to_dma, when: {指令类型: mac, 执行单元: dma}}
        ```
    对象形式是"只交叉有意义的那几对 + 把非法的那几对钉成 illegal"的写法 ——
    全交叉在 4×4 上就是 16 个仓，而真正关心的往往四五个，**非法组合更是会被
    当成正常状态统计**（见 `CrossPair.bins` 的注释）。
    """
    from .vocab import CROSS_LEVEL_ALIASES, split_cross_key
    split = split_cross_key(str(key))
    if not split:
        return None

    if isinstance(level_raw, dict):
        level = canon(str(level_raw.get("level") or ""), CROSS_LEVEL_ALIASES) or "optional"
        return CrossPair(a=split[0], b=split[1], level=level, source="declared",
                         bins=_as_dicts(level_raw.get("bins")),
                         illegal=_as_dicts(level_raw.get("illegal")),
                         cover_id=str(level_raw.get("cover_id") or "").strip(),
                         requirement=str(level_raw.get("requirement") or "").strip())

    level = canon(str(level_raw), CROSS_LEVEL_ALIASES) or "optional"
    return CrossPair(a=split[0], b=split[1], level=level, source="declared")


def _as_dicts(raw: Any) -> list:
    """过滤出 mapping 条目 —— 列表里混进字符串/数字不该让整个交叉解不出来。"""
    return [x for x in (raw if isinstance(raw, list) else ([] if raw is None else [raw]))
            if isinstance(x, dict)]


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
