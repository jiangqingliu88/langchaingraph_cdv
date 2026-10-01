"""功能组织树 —— 骨架本身是否站得住。

树是 case 的落点：叶子生成的 case 才是真在测东西。所以这一组回答三个问题：
  1. 叶子代号唯一吗？      不唯一 → case_id 会撞车，两个不同的 case 同一个名字
  2. 每个叶子被专题打到了吗？没打到 → 那部分结构永远不会被测
  3. 树本身有实质结构吗？    只有一个节点 → 谈不上"组织树"
"""
from __future__ import annotations

from collections import Counter
from typing import List

from ..issues import CATEGORY_ORG_TREE, Issue
from ..specifications import Rule, RuleContext, register


@register
class LeafCodeUnique(Rule):
    id = "org_leaf_code_duplicate"
    severity = "error"
    category = CATEGORY_ORG_TREE
    description = "功能组织树的叶子代号重复 —— case_id 会撞车"

    def check(self, ctx: RuleContext) -> List[Issue]:
        leaves = ctx.model.leaf_nodes
        if not leaves:
            return []
        counts = Counter(n.code for n in leaves)
        out: List[Issue] = []
        for code, n in counts.items():
            if n > 1:
                names = "、".join(x.path_label() for x in leaves if x.code == code)
                out.append(self.issue(
                    f"org_leaf::{code}",
                    f"叶子代号 '{code}' 被 {n} 个节点共用（{names}）—— "
                    f"case_id 会撞车，两个不同的 case 落成同一个名字。"
                    f"请显式声明互不相同的 code"))
        return out


@register
class EveryLeafCovered(Rule):
    id = "org_leaf_uncovered"
    severity = "warning"
    category = CATEGORY_ORG_TREE
    description = "有叶子节点没有被任何专题打到 —— 那部分结构永远不会被测"

    def check(self, ctx: RuleContext) -> List[Issue]:
        if not ctx.model.themes:
            return []                       # 没专题时由 theme 那组规则报
        out: List[Issue] = []
        for node in ctx.model.leaf_nodes:
            if not ctx.cases_for_node(node.id):
                out.append(self.issue(
                    f"org_leaf::{node.id}",
                    f"组织树叶子 '{node.path_label()}'（{node.code}）"
                    f"没有任何专题打到它 —— 这部分结构不会被任何 case 覆盖。"
                    f"在某个专题的 applies_to 里加上它，或明确它会由别的对象负责"))
        return out


@register
class EveryBranchReachable(Rule):
    id = "org_branch_unreachable"
    severity = "warning"
    category = CATEGORY_ORG_TREE
    description = "有分支节点的整棵子树都没有被任何专题打到"

    def check(self, ctx: RuleContext) -> List[Issue]:
        if not ctx.model.themes:
            return []
        out: List[Issue] = []
        for branch in ctx.model.org_root:
            if branch.is_leaf:
                continue
            leaves = branch.leaves()
            if leaves and not any(ctx.cases_for_node(n.id) for n in leaves):
                out.append(self.issue(
                    f"org_branch::{branch.id}",
                    f"分支 '{branch.name}' 下的 {len(leaves)} 个叶子"
                    f"（{'、'.join(n.name for n in leaves)}）全都没有专题覆盖 —— "
                    f"整棵子树是死的。可以直接在 applies_to 里写分支名 '{branch.name}'，"
                    f"会自动展开到它的叶子"))
        return out


@register
class TreeHasStructure(Rule):
    id = "org_tree_flat"
    severity = "info"
    category = CATEGORY_ORG_TREE
    description = "功能组织树只有一层 —— 用扁平列表描述，谈不上层级分解"

    def check(self, ctx: RuleContext) -> List[Issue]:
        model = ctx.model
        if not model.org_root or len(model.tree_nodes) <= 1:
            return []
        if all(not n.children for n in model.org_root):
            return [self.issue(
                "org_tree",
                f"功能组织树是扁平的（{len(model.tree_nodes)} 个同级叶子）。"
                f"若这些节点之间确有层级（如流水段里还有子模块），"
                f"用 children 把它们挂起来，专题就能作用到分支上")]
        return []
