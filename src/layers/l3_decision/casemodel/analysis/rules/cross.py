"""维度交叉 —— 「然后是维度的约束组合」这一层是否自洽。

专题选完范围之后，矩阵负责约束这些维度怎么配。这一组查的是约束本身：
  · 声明的级别和交叉组隐含的级别打架吗
  · 声明禁止交叉，却又被塞进同一个必需组吗
  · 交叉组有两个以上维度吗、规模会炸吗
  · 有维度完全没参与任何交叉吗（它的取值组合永远配不出来）
"""
from __future__ import annotations

from typing import List

from ...domain import CROSS_LEVEL_NAMES
from ...generation import EXPLOSION_THRESHOLD, build_axes, drop_forbidden
from ..issues import CATEGORY_CROSS, Issue
from ..specifications import Rule, RuleContext, register


@register
class CrossLevelMismatch(Rule):
    id = "cross_level_mismatch"
    severity = "warning"
    category = CATEGORY_CROSS
    description = "矩阵声明的级别与交叉组隐含的级别不一致"

    def check(self, ctx: RuleContext) -> List[Issue]:
        matrix = ctx.matrix
        if matrix is None:
            return []
        return self.issues([
            (f"cross::{a}×{b}",
             f"矩阵声明 '{a}×{b}' 为 {CROSS_LEVEL_NAMES.get(declared, declared)}，"
             f"但交叉组 {grp} 把它们标为 "
             f"{CROSS_LEVEL_NAMES.get(grouped, grouped)} —— "
             f"已按矩阵声明处理，建议两边对齐")
            for a, b, declared, grouped, grp in matrix.conflicts])


@register
class CrossConflict(Rule):
    id = "cross_conflict"
    severity = "error"
    category = CATEGORY_CROSS
    description = "矩阵标为禁止交叉，交叉组却把这两个维度放在一起"

    def check(self, ctx: RuleContext) -> List[Issue]:
        matrix = ctx.matrix
        if matrix is None:
            return []
        out: List[Issue] = []
        for grp in ctx.model.cross_groups:
            keys = [d.key for d in grp.dims]
            for i in range(len(keys)):
                for j in range(i + 1, len(keys)):
                    cell = matrix.get(keys[i], keys[j])
                    if cell and cell.level == "forbidden" and cell.source == "declared":
                        out.append(self.issue(
                            f"cross::{keys[i]}×{keys[j]}",
                            f"矩阵声明 '{keys[i]}×{keys[j]}' 为禁止交叉，"
                            f"但交叉组 {grp.key} 又把这两个维度放在一起 —— 二者矛盾"))
        return out


@register
class CrossGroupSize(Rule):
    id = "cross_group_too_small"
    severity = "error"
    category = CATEGORY_CROSS
    description = "交叉组少于两个有效维度"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for grp in ctx.model.cross_groups:
            if len(grp.dims) < 2:
                out.append(self.issue(
                    f"cross_group::{grp.key}",
                    f"交叉组 {grp.key} 只有 {len(grp.dims)} 个有效维度，"
                    f"交叉组至少要两个维度"))
        return out


@register
class CrossGroupExplosion(Rule):
    id = "cross_group_explosion"
    severity = "warning"
    category = CATEGORY_CROSS
    description = "交叉组用 G 方法时组合数过大"

    def check(self, ctx: RuleContext) -> List[Issue]:
        from ...generation.strategies import estimate
        out: List[Issue] = []
        for grp in ctx.model.cross_groups:
            if len(grp.dims) < 2:
                continue
            dims, _dropped = drop_forbidden(ctx.model, grp.dims)
            axes, _derived = build_axes(ctx.model, dims)
            method = grp.method or ("G" if not grp.method else grp.method)
            size = estimate(axes, method, ctx.model.generation.repeat)
            if size > EXPLOSION_THRESHOLD:
                out.append(self.issue(
                    f"cross_group::{grp.key}",
                    f"交叉组 {grp.key}（{'×'.join(d.label for d in grp.dims)}）"
                    f"按 {method} 方法规模约 {size}，建议拆组、降取值点数或改用 RND"))
        return out


@register
class DimensionCrossed(Rule):
    id = "dimension_not_crossed"
    severity = "warning"
    category = CATEGORY_CROSS
    description = "维度没有参与任何交叉组或交叉对"

    def check(self, ctx: RuleContext) -> List[Issue]:
        matrix = ctx.matrix
        if matrix is None:
            return []
        participation = matrix.participation()
        return self.issues([
            (f"dimension::{dim.key}",
             f"维度 '{dim.label}' 没有参与任何交叉组或交叉对 —— "
             f"它的取值不会被任何 case 组合到")
            for dim in ctx.model.dimensions if not participation.get(dim.key)])


@register
class CrossUndeclaredPairs(Rule):
    id = "cross_undeclared_pairs"
    severity = "info"
    category = CATEGORY_CROSS
    description = "有维度对未声明交叉关系，按「不交叉」处理"

    def check(self, ctx: RuleContext) -> List[Issue]:
        matrix = ctx.matrix
        if matrix is None or not matrix.total_pairs():
            return []
        undeclared = matrix.undeclared_count()
        if not undeclared:
            return []
        return [self.issue(
            "cross_matrix",
            f"{matrix.total_pairs()} 对维度里有 {undeclared} 对未声明交叉关系，"
            f"按「不交叉」处理；若其中有必须一起组合的，请补 ★")]
