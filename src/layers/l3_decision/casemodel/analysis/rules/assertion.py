"""断言 ↔ 测试点绑定 —— 失败能不能归因到 TP，取决于这张表。

`assertions[].tp_bindings` 是**一对多**：一条 SVA 可以同时守住多个功能点
（APB 的"控制信号在等待期间稳定"就同时覆盖基本等待、连续等待、写期间稳定）。
绑定表示**关联**，不代表失败必然由全部关联 TP 引起；但没有绑定，失败就
只能停在"某条断言红了"，到不了"哪个验证目标受影响"。

两条规则刻意一紧一松：

  · 绑到了不存在的 TP → **error**（引用错，模型自己的问题）；
  · 部分断言没绑定 → **warning**，且只在"模型已经开始用绑定"时才报 ——
    v1 模型一条都没写，不该因为升级而突然变红。
"""
from __future__ import annotations

from typing import List

from ...framework.naming import iter_value_points
from ..issues import CATEGORY_REFERENCE, Issue
from ..specifications import Rule, RuleContext, register


def _tp_ids(model) -> set:
    return {tp_id for *_rest, tp_id in iter_value_points(model)}


@register
class AssertionTpUnknown(Rule):
    id = "assertion_tp_unknown"
    severity = "error"
    category = CATEGORY_REFERENCE
    description = "断言绑定的测试点不存在（写错 tp_id 或维度改过名）"

    def check(self, ctx: RuleContext) -> List[Issue]:
        known = _tp_ids(ctx.model)
        out: List[Issue] = []
        for assertion in ctx.model.assertions:
            missing = [b["tp_id"] for b in assertion.tp_bindings
                       if b["tp_id"] not in known]
            if missing:
                out.append(self.issue(
                    f"assertion::{assertion.id}",
                    f"断言 '{assertion.name}' 绑定了不存在的测试点："
                    f"{'、'.join(missing)} —— 失败时归因不到任何功能点"))
        return out


@register
class AssertionUnbound(Rule):
    id = "assertion_unbound"
    severity = "warning"
    category = CATEGORY_REFERENCE
    description = "部分断言没有绑定测试点（只有已启用绑定的模型才报）"

    def check(self, ctx: RuleContext) -> List[Issue]:
        assertions = list(ctx.model.assertions or [])
        if not any(a.tp_bindings for a in assertions):
            return []                    # v1 模型：一条绑定都没写，不报
        return [self.issue(
            f"assertion::{a.id}",
            f"断言 '{a.name}' 没有 tp_bindings —— 它失败时无法归因到任何测试点"
            f"（模型里已有一部分断言绑定，说明这是漏写而不是旧格式）")
            for a in assertions if not a.tp_bindings]
