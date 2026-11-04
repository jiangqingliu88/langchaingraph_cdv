"""配置域校验 —— 维度、交叉组、可行性规则（方法学 v2 P3a）。

配置是**功能空间**的一部分（队列深度 8 还是 32），写错的表现和属性维度一样：
引用一个不存在的配置名、某个维度没有取值、组合数爆炸却没人知道。
这些都要在建模期报，不应该等到执行时才"少跑了一组配置"。
"""
from __future__ import annotations

from typing import List

from ..issues import CATEGORY_REFERENCE, Issue
from ..specifications import Rule, RuleContext, register


def _space(ctx: RuleContext):
    return getattr(ctx.model, "config_space", None)


@register
class ConfigDuplicateDimension(Rule):
    id = "config_duplicate_dimension"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "配置维度重名（组合会互相覆盖）"

    def check(self, ctx: RuleContext) -> List[Issue]:
        space = _space(ctx)
        if space is None:
            return []
        names = [d.name for d in space.dimensions]
        dup = sorted({n for n in names if names.count(n) > 1})
        if not dup:
            return []
        return [self.issue("config_space",
                           f"配置维度重名：{'、'.join(dup)}")]


@register
class ConfigDimensionEmpty(Rule):
    id = "config_dimension_empty"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "配置维度没有取值"

    def check(self, ctx: RuleContext) -> List[Issue]:
        space = _space(ctx)
        if space is None:
            return []
        return [self.issue(f"config::{d.name}",
                           f"配置维度 '{d.name}' 没有取值 —— 组合恒为空")
                for d in space.dimensions if not d.values]


@register
class ConfigRefUnknown(Rule):
    id = "config_ref_unknown"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "交叉组 / 可行性规则引用了未声明的配置维度或取值"

    def check(self, ctx: RuleContext) -> List[Issue]:
        space = _space(ctx)
        if space is None:
            return []
        out: List[Issue] = []
        out.extend(_group_issues(space))
        out.extend(_feasibility_issues(space))
        return out


def _group_issues(space) -> List[Issue]:
    out: List[Issue] = []
    for group in space.cross_groups:
        for name in group.get("dimensions") or []:
            if space.dimension(str(name)) is None:
                out.append(Issue(
                    severity="error", rule="config_ref_unknown",
                    target=f"config_cross::{group.get('id') or name}",
                    message=f"配置交叉组引用了未声明的维度 '{name}'",
                    category=CATEGORY_REFERENCE))
    return out


def _feasibility_issues(space) -> List[Issue]:
    out: List[Issue] = []
    for rule in space.feasibility:
        cond = rule.get("when")
        if not isinstance(cond, dict):
            continue
        for name, value in cond.items():
            dim = space.dimension(str(name))
            if dim is None:
                out.append(Issue(
                    severity="error", rule="config_ref_unknown",
                    target=f"config_rule::{rule.get('id') or name}",
                    message=f"可行性规则引用了未声明的配置维度 '{name}'",
                    category=CATEGORY_REFERENCE))
                continue
            if dim.values and value not in dim.values:
                out.append(Issue(
                    severity="error", rule="config_ref_unknown",
                    target=f"config_rule::{rule.get('id') or name}",
                    message=f"可行性规则里 {name}={value!r} 不在该维度的取值表里",
                    category=CATEGORY_REFERENCE))
    return out


@register
class ConfigCombinationCap(Rule):
    id = "config_combination_cap"
    severity = "warning"
    category = CATEGORY_REFERENCE
    description = "配置组合数超过上限，会被截断"

    def check(self, ctx: RuleContext) -> List[Issue]:
        space = _space(ctx)
        if space is None:
            return []
        total = 1
        for dim in space.dimensions:
            total *= max(1, len(dim.values))
        if total <= space.max_combinations:
            return []
        return [self.issue(
            "config_space",
            f"配置组合有 {total} 种，超过 max_combinations="
            f"{space.max_combinations} —— 只会枚举前 {space.max_combinations} 种，"
            f"其余截断（要覆盖请提高上限或缩小配置空间）")]
