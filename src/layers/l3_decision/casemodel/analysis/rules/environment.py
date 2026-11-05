"""环境指纹与检查项 —— 文档九、十节。

这两块是「最容易被遗漏」的两层，也是「可复现」定位的直接落点：

  环境指纹   case 不以它为主体，但执行时必须带上，失败才可复现。
             缺一个必需键，那条 case 就永远复现不了。
  检查项     一个 case 往往不止一种检查（功能 / 白盒 / 性能）。
             没挂检查的 case 跑过也不知道验证了什么。

按维度/字段名去推断该挂哪种检查（`check_suggested`）是启发式，
所以是 info 级：它提示「你这里有队列/资源字段，是不是该上 CHECK-WBOX」，
而不是替人做决定。
"""
from __future__ import annotations

from typing import List

from ...domain import CHECK_NAMES, ENV_KEYS, ENV_KEY_NAMES
from ..issues import CATEGORY_ENVIRONMENT, Issue
from ..specifications import Rule, RuleContext, register
from .orthogonality import CHECK_HINTS


@register
class EnvironmentDeclared(Rule):
    id = "environment_not_declared"
    severity = "warning"
    category = CATEGORY_ENVIRONMENT
    description = "未声明必需的环境指纹 —— 失败 case 无法复现"

    def check(self, ctx: RuleContext) -> List[Issue]:
        if ctx.model.env_required:
            return []
        return [self.issue(
            "environment",
            "未声明 environment.required —— 没有环境指纹的 case 失败后无法复现，"
            "建议至少声明 rtl_version / constraint_version / seed")]


@register
class EnvironmentDefault(Rule):
    id = "environment_key_without_default"
    severity = "info"
    category = CATEGORY_ENVIRONMENT
    description = "必需环境键没有缺省值，执行时需外部提供"

    def check(self, ctx: RuleContext) -> List[Issue]:
        return self.issues([
            (f"environment::{k}",
             f"必需环境键 '{ENV_KEY_NAMES.get(k, k)}' 没有缺省值，执行时需由外部提供")
            for k in ctx.model.env_required
            if k not in ctx.model.case_defaults.environment])


@register
class CaseHasEnvironment(Rule):
    id = "case_missing_environment_key"
    severity = "error"
    category = CATEGORY_ENVIRONMENT
    description = "case 缺必需的环境键 —— 这些 case 失败后不可复现"

    def check(self, ctx: RuleContext) -> List[Issue]:
        cases = ctx.generation.cases
        if not cases:
            return []
        out: List[Issue] = []
        for k in ctx.model.env_required:
            missing = sum(1 for c in cases
                          if k not in c.environment
                          or c.environment.get(k) in (None, ""))
            if missing:
                out.append(self.issue(
                    f"environment::{k}",
                    f"{missing}/{len(cases)} 个 case 缺必需环境键 "
                    f"'{ENV_KEY_NAMES.get(k, k)}'，这些 case 失败后不可复现"))
        return out


@register
class EnvironmentKnownKeys(Rule):
    id = "environment_unknown_key"
    severity = "warning"
    category = CATEGORY_ENVIRONMENT
    description = "环境指纹里有未登记的键，不会被写进 case"

    def check(self, ctx: RuleContext) -> List[Issue]:
        return self.issues([
            (f"environment::{k}",
             f"环境指纹里有未登记的键 '{k}'，不会被写进 case —— 已知键："
             f"{' / '.join(ENV_KEYS)}")
            for k in ctx.model.env_unknown_keys])


@register
class ChecksDeclared(Rule):
    id = "checks_not_declared"
    severity = "warning"
    category = CATEGORY_ENVIRONMENT
    description = "未声明任何 L6 检查项"

    def check(self, ctx: RuleContext) -> List[Issue]:
        if ctx.model.checks:
            return []
        return [self.issue(
            "checks",
            "未声明任何 L6 检查项 —— 一个 case 往往不止一种检查"
            "（功能 / 白盒 / 性能），缺了检查项就等于没有验证目标")]


@register
class CheckNeverUsed(Rule):
    id = "check_never_used"
    severity = "info"
    category = CATEGORY_ENVIRONMENT
    description = "检查项声明了但没有 case 挂上它"

    def check(self, ctx: RuleContext) -> List[Issue]:
        used = {c for case in ctx.generation.cases for c in case.checks}
        return self.issues([
            (f"check::{cid}",
             f"检查项 {cid}（{CHECK_NAMES.get(cid, '')}）声明了但没有任何 case 挂上它")
            for cid in ctx.model.checks if cid not in used])


@register
class CaseHasChecks(Rule):
    id = "case_without_check"
    severity = "error"
    category = CATEGORY_ENVIRONMENT
    description = "case 没有挂任何检查项 —— 跑过也不知道验证了什么"

    def check(self, ctx: RuleContext) -> List[Issue]:
        cases = ctx.generation.cases
        if not cases:
            return []
        blank = sum(1 for c in cases if not c.checks)
        if not blank:
            return []
        return [self.issue(
            "checks",
            f"{blank}/{len(cases)} 个 case 没有挂任何检查项，"
            f"这些 case 跑过也不知道验证了什么")]


@register
class CheckSuggested(Rule):
    id = "check_suggested"
    severity = "info"
    category = CATEGORY_ENVIRONMENT
    description = "模型里有与某类检查相关的维度/字段，但该检查未声明"

    def check(self, ctx: RuleContext) -> List[Issue]:
        model = ctx.model
        corpus = " ".join(
            [d.label for d in model.dimensions]
            + [f.name for f in model.all_fields]
            + [f.description for f in model.all_fields]
            + [d.description for d in model.dimensions]
            + [n.name for n in model.tree_nodes]
            + [t.label for t in model.themes]).upper()
        out: List[Issue] = []
        for check, hints in CHECK_HINTS.items():
            if check in model.checks:
                continue
            if any(h.upper() in corpus for h in hints):
                out.append(self.issue(
                    f"check::{check}",
                    f"模型里有与「{CHECK_NAMES.get(check, check)}」相关的"
                    f"维度/字段/节点，但 {check} 未在 checks 里声明"))
        return out
