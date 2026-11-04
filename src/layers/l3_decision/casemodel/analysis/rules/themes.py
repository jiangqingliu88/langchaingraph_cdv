"""专题 —— P0/P1/P2 分层是否成立、范围是否自相矛盾。

专题是横切在功能组织树上的验证关注点，它先选目标与范围，
维度交叉矩阵再去约束这些维度怎么配。所以这一组查的是「选得对不对」：
  · 优先级阶梯断了吗（有 P0/P2 没 P1）
  · 专题之间重叠了吗（同样的目标+维度+方法 → 会生成字段取值完全一样的 case）
  · 有维度没被任何专题选中吗（它的取值永远不会被覆盖）
  · 用 SPCL 却推不动边界吗（关键字段没声明 boundary）
  · 专题选了互斥的两个维度吗（和 cross_matrix 的禁止交叉打架）
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

from ...domain import Theme, priority_gaps
from ..issues import CATEGORY_THEME, Issue
from ..specifications import Rule, RuleContext, register


@register
class PriorityLadder(Rule):
    id = "theme_priority_gap"
    severity = "warning"
    category = CATEGORY_THEME
    description = "专题优先级有断层（如只有 P0 和 P2）"

    def check(self, ctx: RuleContext) -> List[Issue]:
        missing = priority_gaps(ctx.themes)
        if not missing:
            return []
        have = "、".join(sorted({t.priority for t in ctx.themes}))
        return [self.issue(
            "themes",
            f"专题优先级是 {have}，缺 {'、'.join(missing)} —— "
            f"阶梯断了。要么补齐中间轮次，要么说明它确实不需要那一轮")]


@register
class DuplicateThemeId(Rule):
    id = "theme_duplicate_id"
    severity = "error"
    category = CATEGORY_THEME
    description = "专题 id 重复"

    def check(self, ctx: RuleContext) -> List[Issue]:
        counts: Dict[str, int] = defaultdict(int)
        for t in ctx.themes:
            counts[t.key] += 1
        return [self.issue(f"theme::{key}",
                           f"专题 id '{key}' 出现了 {n} 次，无法区分")
                for key, n in counts.items() if n > 1]


@register
class ThemeOverlap(Rule):
    id = "theme_overlap"
    severity = "warning"
    category = CATEGORY_THEME
    description = "两个专题的目标节点 / 维度集合 / 方法完全相同 —— 会生成重复 case"

    def check(self, ctx: RuleContext) -> List[Issue]:
        """文档十二节：对象+子对象+字段取值相同就是重复。

        专题层面能提前发现这件事：两个专题若打同一批节点、用同一批维度、
        同一个方法，就会生成字段取值完全一样的 case，只是 case_id 不同。
        """
        buckets: Dict[Tuple, List[Theme]] = defaultdict(list)
        for theme in ctx.themes:
            targets = tuple(sorted(n.code for n in theme.nodes)) \
                if theme.is_structural else ()
            key = (targets, tuple(sorted(d.key for d in theme.dims)),
                   theme.method or "inherit")
            buckets[key].append(theme)
        out: List[Issue] = []
        for key, themes in buckets.items():
            if len(themes) < 2:
                continue
            ids = "、".join(t.key for t in themes)
            targets, dims, method = key
            out.append(self.issue(
                f"theme::{ids}",
                f"{len(themes)} 个专题（{ids}）的「目标节点 + 维度集合 + 方法」"
                f"完全相同（目标 {len(targets)} 个、维度 {len(dims)} 个、"
                f"方法 {method}）—— 会生成字段取值完全一致的 case，"
                f"文档十二节称之为重复。合并它们，或让各自的范围/方法区别开"))
        return out


@register
class DimensionCoveredBySomeTheme(Rule):
    id = "theme_dimension_unused"
    severity = "warning"
    category = CATEGORY_THEME
    description = "有维度没有被任何专题选中 —— 它的取值永远不会被覆盖"

    def check(self, ctx: RuleContext) -> List[Issue]:
        if not ctx.themes:
            return []
        used = {d.key for t in ctx.themes for d in t.dims}
        out: List[Issue] = []
        for dim in ctx.model.dimensions:
            if dim.key not in used:
                out.append(self.issue(
                    f"dimension::{dim.key}",
                    f"维度 '{dim.label}' 没有被任何专题的 dimensions 选中 —— "
                    f"它的取值不会被任何 case 覆盖。"
                    f"加进某个专题，或把它标成由别的对象负责"))
        return out


@register
class SpclNeedsBoundary(Rule):
    id = "theme_spcl_without_boundary"
    severity = "warning"
    category = CATEGORY_THEME
    description = "专题用 SPCL 专项，但它的字段没声明 boundary —— 推不到边界"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for theme in ctx.themes:
            methods = [theme.method] if theme.method else ctx.model.generation.methods
            if "SPCL" not in methods:
                continue
            limp = [f for d in theme.dims for f in d.fields
                    if not any(p.is_edge for p in f.value_points())]
            if limp:
                out.append(self.issue(
                    f"theme::{theme.key}",
                    f"专题 '{theme.label}' 用 SPCL 专项，但字段 "
                    f"{'、'.join(f.name for f in limp)} 没有声明任何 boundary —— "
                    f"专项推不动这些字段，等于退化成定向。"
                    f"给它们加 boundary（范围型至少写端点）"))
        return out


@register
class ThemeForbiddenPair(Rule):
    id = "theme_forbidden_pair"
    severity = "error"
    category = CATEGORY_THEME
    description = "专题同时选了被标为禁止交叉的两个维度"

    def check(self, ctx: RuleContext) -> List[Issue]:
        matrix = ctx.matrix
        if matrix is None:
            return []
        forbidden = {frozenset(p) for p in matrix.forbidden_pairs()}
        if not forbidden:
            return []
        out: List[Issue] = []
        for theme in ctx.themes:
            keys = [d.key for d in theme.dims]
            for i in range(len(keys)):
                for j in range(i + 1, len(keys)):
                    if frozenset((keys[i], keys[j])) in forbidden:
                        out.append(self.issue(
                            f"theme::{theme.key}",
                            f"专题 '{theme.label}' 同时选了 '{keys[i]}' 与 "
                            f"'{keys[j]}'，但 cross_matrix 把它们标为禁止交叉 —— "
                            f"模型自相矛盾。生成时已保留前者、剔除后者，"
                            f"请把该维度从这个专题里去掉，或调整矩阵级别"))
        return out


@register
class ThemeNeverGenerated(Rule):
    id = "theme_never_generated"
    severity = "info"
    category = CATEGORY_THEME
    description = "专题被 generation 的优先级/专题选择器排除在外，没有生成 case"

    def check(self, ctx: RuleContext) -> List[Issue]:
        if not ctx.themes:
            return []
        gen = ctx.model.generation
        if not gen.priorities and not gen.themes:
            return []
        generated = {c.theme for c in ctx.generation.cases}
        out: List[Issue] = []
        for theme in ctx.themes:
            if theme.id not in generated:
                reason = (f"优先级 {theme.priority} 不在 generation.priorities "
                          f"{gen.priorities} 里" if gen.priorities
                          and not gen.allows_priority(theme.priority)
                          else "不在 generation.themes 里")
                out.append(self.issue(
                    f"theme::{theme.key}",
                    f"专题 '{theme.label}' 本次没有生成 case（{reason}）—— "
                    f"是有意缩小范围，还是漏了？"))
        return out


@register
class NoThemesDeclared(Rule):
    id = "themes_not_declared"
    severity = "warning"
    category = CATEGORY_THEME
    description = "模型没有声明 themes —— 退回按交叉组生成"

    def check(self, ctx: RuleContext) -> List[Issue]:
        if ctx.themes:
            return []
        return [self.issue(
            "themes",
            "未声明 themes —— 没有验证专题，生成会退回按交叉组组合。"
            "专题是「这一轮打哪些节点、用哪些维度」的载体，"
            "缺了它就没有 P0/P1/P2 的分轮次推进")]


@register
class EmptyTheme(Rule):
    id = "theme_no_dimension"
    severity = "error"
    category = CATEGORY_THEME
    description = "专题没有任何可用维度，生成不出 case"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for theme in ctx.themes:
            if not theme.dims:
                detail = ("（applies_to 全部悬空）" if theme.unresolved_nodes
                          else "（dimensions 全部悬空）" if theme.unresolved_dims
                          else "")
                out.append(self.issue(
                    f"theme::{theme.key}",
                    f"专题 '{theme.label}' 没有任何可用维度{detail}，生成不出 case"))
        return out
