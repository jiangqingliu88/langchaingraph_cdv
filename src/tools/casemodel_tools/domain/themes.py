"""专题 —— 横切在功能组织树上的验证关注点，按 P0/P1/P2 分层。

专题是「这一轮验证要打树上的哪些节点、用哪些维度、什么方法」，
层级在维度之上：它先选目标与范围，维度交叉矩阵再去约束这些维度怎么配。
这就是「P0/P1/P2 专题作用于功能组织树，然后是维度的约束组合」的先后关系。

三类的区别**全部**由两个字段决定，不设独立的 kind 字段 ——
免得「字段说的」和「标签说的」两处打架：

    applies_to   留空       → 不作用树（错误和异常 / 性能常稳这类全局关注点）
                 非空 / ["*"] → 作用于树（指向分支时展开到它的叶子）

    dimensions   留空 / ["*"] → 各维度随机组合
                 非空         → 限定维度集合

于是四象限都有意义，kind / dim_scope 都是从这两个字段**派生**出来的视图。
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any, List, Optional

from .dimensions import Dimension
from .nodes import OrgNode
from .vocab import (DEFAULT_PRIORITY, THEME_DIM_SCOPES, THEME_KINDS, as_list,
                    canon, is_wildcard, normalize_priority, priority_label,
                    priority_rank)


@dataclass
class Theme:
    """一个专题。"""
    id: str
    name: str
    priority: str = DEFAULT_PRIORITY
    applies_to: List[str] = _field(default_factory=list)     # 原始引用
    dimensions: List[str] = _field(default_factory=list)     # 原始引用
    method: str = ""
    checks: List[str] = _field(default_factory=list)
    repeat: Optional[int] = None
    expected_result: str = ""
    description: str = ""
    # ── resolve() 之后回填 ──
    nodes: List[OrgNode] = _field(default_factory=list)      # 已展开到叶子
    dims: List[Dimension] = _field(default_factory=list)
    unresolved_nodes: List[str] = _field(default_factory=list)
    unresolved_dims: List[str] = _field(default_factory=list)

    # ── 身份 ──

    @property
    def key(self) -> str:
        return self.id or self.name

    @property
    def label(self) -> str:
        return self.name or self.id

    @property
    def rank(self) -> int:
        return priority_rank(self.priority)

    @property
    def priority_label(self) -> str:
        return priority_label(self.priority)

    # ── 派生视图：由 applies_to / dimensions 决定，不另存状态 ──

    @property
    def applies_to_all(self) -> bool:
        return any(is_wildcard(r) for r in self.applies_to)

    @property
    def is_structural(self) -> bool:
        """是否作用于功能组织树。applies_to 留空 = 正交专题。"""
        return bool(self.applies_to)

    @property
    def kind(self) -> str:
        return "structural" if self.is_structural else "orthogonal"

    @property
    def kind_name(self) -> str:
        return THEME_KINDS[self.kind]

    @property
    def covers_all_dimensions(self) -> bool:
        return not self.dimensions or any(is_wildcard(r) for r in self.dimensions)

    @property
    def dim_scope(self) -> str:
        return "all" if self.covers_all_dimensions else "restricted"

    @property
    def dim_scope_name(self) -> str:
        return THEME_DIM_SCOPES[self.dim_scope]

    @property
    def is_random(self) -> bool:
        """各维度随机组合 —— 不限定维度，就是「拿全部维度随机配」。"""
        return self.covers_all_dimensions

    @property
    def target_label(self) -> str:
        """作用目标的人读描述。"""
        if not self.is_structural:
            return "不作用功能组织树"
        if self.applies_to_all:
            return "全树"
        if self.nodes:
            return "、".join(n.name for n in self.nodes)
        return "、".join(self.applies_to)

    @property
    def dimension_label(self) -> str:
        if self.covers_all_dimensions:
            return "全部维度"
        if self.dims:
            return "、".join(d.label for d in self.dims)
        return "、".join(self.dimensions)

    def targets(self) -> List[Optional[OrgNode]]:
        """生成时的目标节点列表。

        不作用树的专题返回 [None] —— 它照样要生成 case，只是 case 不挂任何树节点。
        """
        if not self.is_structural:
            return [None]
        return list(self.nodes) or [None]

    def sort_key(self):
        """按优先级排序，同级保持声明顺序。"""
        return (self.rank, self.id)


def build_theme(item: Any, index: int) -> Optional[Theme]:
    from .vocab import CHECK_ALIASES, METHOD_ALIASES
    if not isinstance(item, dict):
        return None
    tid = str(item.get("id") or "").strip()
    name = str(item.get("name") or tid).strip()
    if not tid and not name:
        return None
    repeat: Optional[int] = None
    if item.get("repeat") is not None:
        try:
            repeat = max(1, int(item["repeat"]))
        except (TypeError, ValueError):
            repeat = None
    return Theme(
        id=tid or f"TH-{index:02d}",
        name=name,
        priority=normalize_priority(item.get("priority")),
        applies_to=[str(s) for s in as_list(item.get("applies_to"))],
        dimensions=[str(s) for s in as_list(item.get("dimensions"))],
        method=canon(str(item.get("method") or ""), METHOD_ALIASES) or "",
        checks=[c for c in (canon(str(x), CHECK_ALIASES)
                            for x in as_list(item.get("checks"))) if c],
        repeat=repeat,
        expected_result=str(item.get("expected_result") or ""),
        description=str(item.get("description") or ""),
    )


def sort_themes(themes: List[Theme]) -> List[Theme]:
    return sorted(themes, key=lambda t: t.sort_key())


def priority_gaps(themes: List[Theme]) -> List[str]:
    """优先级空洞：有 P0 和 P2 却没有 P1 —— 阶梯断了，说明分层没想清楚。"""
    ranks = sorted({t.rank for t in themes if t.rank < 90})
    if len(ranks) < 2:
        return []
    missing = [f"P{r}" for r in range(ranks[0], ranks[-1] + 1) if r not in ranks]
    return missing
