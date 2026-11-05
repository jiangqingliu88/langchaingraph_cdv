"""行为域校验 —— 状态 / 事件引用、检查点、节点重名（方法学 v2 P1）。

行为 TP 的价值是"走过这条边/这段序列"，所以三条硬约束：

  1. 迁移与序列引用的事件、状态必须存在（写错名字 = 一条永远走不到的边）；
  2. 每个节点至少有一个检查（走过 ≠ 验过；没有 check 的边只是覆盖率装饰）；
  3. 节点 id 唯一（TP 主键由它派生）。

模型没写 `behavior:` 时一条都不报 —— v1 行为不变。
"""
from __future__ import annotations

from typing import List

from ..issues import CATEGORY_REFERENCE, Issue
from ..specifications import Rule, RuleContext, register


def _behavior(ctx: RuleContext):
    return getattr(ctx.model, "behavior", None)


@register
class BehaviorRefUnknown(Rule):
    id = "behavior_ref_unknown"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "行为节点引用了未声明的状态 / 事件"

    def check(self, ctx: RuleContext) -> List[Issue]:
        behavior = _behavior(ctx)
        if behavior is None:
            return []
        states = set(behavior.states)
        events = set(behavior.events)
        out: List[Issue] = []
        for transition in behavior.transitions:
            missing = []
            if states and transition.from_state not in states:
                missing.append(f"from={transition.from_state}")
            if states and transition.to_state not in states:
                missing.append(f"to={transition.to_state}")
            if events and transition.event not in events:
                missing.append(f"event={transition.event}")
            if missing:
                out.append(self.issue(
                    f"behavior::{transition.id}",
                    f"迁移 '{transition.id}' 引用了未声明的 "
                    f"{'、'.join(missing)}"))
        for sequence in behavior.sequences:
            for index, step in enumerate(sequence.steps, start=1):
                event = str(step.get("event") or "")
                if events and event not in events:
                    out.append(self.issue(
                        f"behavior::{sequence.id}",
                        f"序列 '{sequence.id}' 第 {index} 步的事件 "
                        f"'{event}' 未声明"))
        for prop in behavior.temporal:
            if events and prop.trigger and prop.trigger not in events:
                out.append(self.issue(
                    f"behavior::{prop.id}",
                    f"时序性质 '{prop.id}' 的 trigger '{prop.trigger}' 未声明"))
        return out


@register
class BehaviorNoCheck(Rule):
    id = "behavior_no_check"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "行为节点没有检查点（走过不等于验过）"

    def check(self, ctx: RuleContext) -> List[Issue]:
        behavior = _behavior(ctx)
        if behavior is None or behavior.checks:
            return []
        out: List[Issue] = []
        for transition in behavior.transitions:
            if not transition.checks:
                out.append(self.issue(
                    f"behavior::{transition.id}",
                    f"迁移 '{transition.id}' 没有 checks —— "
                    f"走过这条边不代表验过（加 checks 或给行为级默认 checks）"))
        for sequence in behavior.sequences:
            if not sequence.expects:
                out.append(self.issue(
                    f"behavior::{sequence.id}",
                    f"序列 '{sequence.id}' 没有 expects —— 步骤跑完不等于结果对"))
        for prop in behavior.temporal:
            if not prop.checks:
                out.append(self.issue(
                    f"behavior::{prop.id}",
                    f"时序性质 '{prop.id}' 没有 checks —— 触发/响应无法判定"))
        return out


@register
class BehaviorDuplicateNode(Rule):
    id = "behavior_duplicate_node"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "行为节点 id 重复（TP 主键会撞车）"

    def check(self, ctx: RuleContext) -> List[Issue]:
        behavior = _behavior(ctx)
        if behavior is None:
            return []
        ids = behavior.node_ids()
        dup = sorted({node for node in ids if ids.count(node) > 1})
        if not dup:
            return []
        return [self.issue(
            "behavior",
            f"行为节点 id 重复：{'、'.join(dup)} —— 由它派生的 tp_id 会撞车")]
