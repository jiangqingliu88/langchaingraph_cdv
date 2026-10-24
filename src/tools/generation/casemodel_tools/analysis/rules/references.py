"""引用完整性 —— 引用的东西到底存不存在。

这一组是最基础的一层：模型里任何一处字符串引用（关系表、交叉矩阵、交叉组、
专题的 applies_to / dimensions、生成范围）都必须能绑到一个真实对象上。
绑不上就是硬错误 —— 它会让「看起来生效实则失效」，与「可复现·可审计」冲突。
"""
from __future__ import annotations

from typing import List

from ..issues import CATEGORY_REFERENCE, Issue
from ..specifications import Rule, RuleContext, register


@register
class UnknownDimensionRef(Rule):
    id = "unknown_dimension_ref"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "交叉矩阵 / 交叉组 / 生成范围引用了不存在的维度"

    def check(self, ctx: RuleContext) -> List[Issue]:
        model = ctx.model
        out: List[Issue] = []
        for ref_a, ref_b in model.resolve_report.cross_refs:
            missing = [r for r, d in ((ref_a, model.dimension(ref_a)),
                                      (ref_b, model.dimension(ref_b))) if d is None]
            out.append(self.issue(
                f"cross_matrix::{ref_a}×{ref_b}",
                f"交叉矩阵引用了不存在的维度 {' / '.join(repr(m) for m in missing)}"
                f"（{ref_a}×{ref_b}），该格子无法落到任何维度上"))
        for grp_key, ref in model.resolve_report.group_refs:
            out.append(self.issue(f"cross_group::{grp_key}",
                                  f"交叉组 {grp_key} 引用了不存在的维度 '{ref}'"))
        for ref in model.resolve_report.gen_dims:
            out.append(self.issue("generation.dimensions",
                                  f"生成范围引用了不存在的维度 '{ref}'"))
        return out


@register
class UnknownFieldRef(Rule):
    id = "unknown_field_ref"
    severity = "warning"
    category = CATEGORY_REFERENCE
    description = "字段关系表引用了不存在的字段（该条关系不生效）"

    def check(self, ctx: RuleContext) -> List[Issue]:
        return self.issues([
            (f"dimension::{dim_key}",
             f"字段关系表引用了不存在的字段 '{ref}'，该条关系不会生效")
            for dim_key, ref in ctx.model.resolve_report.relation_refs])


@register
class UnknownLinkageRef(Rule):
    id = "unknown_linkage_ref"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "联动型字段的 linked_to 指向不存在的字段"

    def check(self, ctx: RuleContext) -> List[Issue]:
        return self.issues([
            (f"field::{field_q}",
             f"联动型字段的 linked_to 指向不存在的字段 '{ref}'，取值无法回填")
            for field_q, ref in ctx.model.resolve_report.linkage_refs])


@register
class UnknownTreeNodeRef(Rule):
    id = "unknown_tree_node_ref"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "维度 / 交叉组 / 专题 / 生成范围引用了不存在的组织树节点"

    def check(self, ctx: RuleContext) -> List[Issue]:
        rep = ctx.model.resolve_report
        out: List[Issue] = []
        for dim_key, ref in rep.dim_sub_objects:
            out.append(self.issue(f"dimension::{dim_key}",
                                  f"维度限定的组织树节点 '{ref}' 不存在"))
        for grp_key, ref in rep.group_sub_objects:
            out.append(self.issue(f"cross_group::{grp_key}",
                                  f"交叉组限定的组织树节点 '{ref}' 不存在"))
        for theme_key, ref in rep.theme_nodes:
            out.append(self.issue(f"theme::{theme_key}",
                                  f"专题的 applies_to 引用了不存在的组织树节点 "
                                  f"'{ref}' —— 该专题会漏掉这部分覆盖"))
        for ref in dict.fromkeys(rep.gen_sub_objects):
            out.append(self.issue("generation.sub_objects",
                                  f"生成范围引用了不存在的组织树节点 '{ref}'"))
        return out


@register
class UnknownThemeRef(Rule):
    id = "unknown_theme_ref"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "生成范围引用了不存在的专题"

    def check(self, ctx: RuleContext) -> List[Issue]:
        return self.issues([
            ("generation.themes", f"生成范围引用了不存在的专题 '{ref}'")
            for ref in ctx.model.resolve_report.gen_themes])


@register
class UnknownCrossGroupRef(Rule):
    id = "unknown_cross_group_ref"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "生成范围引用了不存在的交叉组"

    def check(self, ctx: RuleContext) -> List[Issue]:
        return self.issues([
            ("generation.groups", f"生成范围引用了不存在的交叉组 '{ref}'")
            for ref in ctx.model.resolve_report.gen_groups])


@register
class AmbiguousDimensionRef(Rule):
    id = "ambiguous_dimension_ref"
    severity = "warning"
    category = CATEGORY_REFERENCE
    description = "简称同时匹配多个维度，已取第一个"

    def check(self, ctx: RuleContext) -> List[Issue]:
        return self.issues([
            (f"reference::{ref}",
             f"'{ref}' 同时匹配多个维度（{' / '.join(cands)}），"
             f"已取第一个，建议改用完整维度名或 id")
            for ref, cands in ctx.model.resolve_report.ambiguous_dims])


@register
class DerivedCodes(Rule):
    id = "derived_code"
    severity = "info"
    category = CATEGORY_REFERENCE
    description = "对象或树节点未声明 ASCII 代号，case_id 靠推导"

    def check(self, ctx: RuleContext) -> List[Issue]:
        model = ctx.model
        out: List[Issue] = []
        if not model.object_code_declared:
            out.append(self.issue(
                f"object::{model.object}",
                f"未声明 object_code，已推导为 '{model.object_code}'，"
                f"case_id 形如 TC-{model.object_code}-…"))
        for node in model.tree_nodes:
            if node.code_source in ("id", "fallback"):
                why = ("名字里没有可用的 ASCII" if node.code_source == "id"
                       else "名字与 id 都推不出代号")
                out.append(self.issue(
                    f"org_node::{node.id}",
                    f"组织树节点 '{node.path_label()}' 没声明 code，且{why}，"
                    f"case_id 退化为 …-{node.code}-…，建议显式声明 code"))
        return out
