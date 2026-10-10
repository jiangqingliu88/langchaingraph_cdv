"""层级正交性 —— 文档十八、十九节点名的四类错位。

判据只有一条：**同一个信息只能存在于一个层级**。

    把字段当维度   维度名以另一个维度的字段取值开头（'尾拍反压'）
    把维度当对象   对象名与某个维度名撞车（对象'反压比例'）
    把方法当维度   维度名里含方法词（'随机反压'）
    把检查当对象   对象名里含检查词（对象'白盒检查'）

用 startswith 而不是 in 来判「把字段当维度」：文档的反例是「维度：尾拍反压」——
取值被提上去当了维度名；而 '反压持续时间' 里的 '持续' 只是构词成分，
不是被提上来的取值，用 in 会把它误报。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional, Sequence, Tuple

from ..issues import CATEGORY_ORTHOGONAL, Issue
from ..specifications import Rule, RuleContext, register

# 「把方法当维度 / 当取值」的信号词
METHOD_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("随机", "RND"), ("RANDOM", "RND"), ("定向", "D"), ("DIRECT", "D"),
    ("组合", "G"), ("COMBIN", "G"), ("笛卡尔", "G"), ("重放", "RPLY"),
    ("REPLAY", "RPLY"), ("专项", "SPCL"), ("SPECIAL", "SPCL"), ("变异", "SPCL"),
)

# 「把检查当对象 / 当维度」的信号词
CHECK_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("白盒", "CHECK-WBOX"), ("WHITEBOX", "CHECK-WBOX"), ("WBOX", "CHECK-WBOX"),
    ("覆盖率", "CHECK"), ("COVERAGE", "CHECK"), ("检查", "CHECK"),
    ("CHECK", "CHECK"),
)

# 检查项建议信号词（文档九节：功能 / 白盒 / 性能三种检查）
CHECK_HINTS = {
    "CHECK-WBOX": ("队列", "资源", "深度", "计数", "水位", "缓存", "buffer", "fifo",
                   "queue", "credit", "信用", "占用", "余量", "仲裁"),
    "CHECK-PERF": ("持续", "吞吐", "延迟", "带宽", "比例", "恢复", "性能", "速率",
                   "latency", "throughput", "bandwidth", "recovery", "常稳"),
    "CHECK-FUNC": ("完整", "丢失", "顺序", "正确", "一致", "order", "loss",
                   "correct", "integrity", "异常", "错误"),
}

_SHORT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def contains_keyword(text: str,
                     keywords: Sequence[Tuple[str, str]]) -> Optional[str]:
    upper = (text or "").upper()
    for kw, _code in keywords:
        if kw.upper() in upper:
            return kw
    return None


def method_code_for(kw: str) -> str:
    for k, code in METHOD_KEYWORDS:
        if k == kw:
            return code
    return "RND"


@register
class MethodAsObject(Rule):
    id = "method_as_object"
    severity = "error"
    category = CATEGORY_ORTHOGONAL
    description = "对象名里含方法词 —— 方法是 L5 生成属性，不是验证主体"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for probe in [p for p in (ctx.model.object, ctx.model.object_cn) if p]:
            kw = contains_keyword(probe, METHOD_KEYWORDS)
            if kw:
                code = method_code_for(kw)
                out.append(self.issue(
                    f"object::{probe}",
                    f"对象名 '{probe}' 里含方法词 '{kw}' —— 方法是 L5 生成属性，"
                    f"不是验证主体。正确做法：用 method={code} "
                    f"表达，对象只描述主体"))
        return out


@register
class CheckAsObject(Rule):
    id = "check_as_object"
    severity = "error"
    category = CATEGORY_ORTHOGONAL
    description = "对象名里含检查词 —— 检查是 L6 属性，不是验证主体"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for probe in [p for p in (ctx.model.object, ctx.model.object_cn) if p]:
            kw = contains_keyword(probe, CHECK_KEYWORDS)
            if kw:
                out.append(self.issue(
                    f"object::{probe}",
                    f"对象名 '{probe}' 里含检查词 '{kw}' —— 检查是 L6 属性，"
                    f"不是验证主体。正确做法：把检查放进 checks "
                    f"（如 CHECK-WBOX / CHECK-PERF）"))
        return out


@register
class DimensionAsObject(Rule):
    id = "dimension_as_object"
    severity = "error"
    category = CATEGORY_ORTHOGONAL
    description = "对象名与某个维度名撞车 —— 维度是对象下的会变化条件"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for probe in [p for p in (ctx.model.object, ctx.model.object_cn) if p]:
            for dim in ctx.model.dimensions:
                if not dim.name:
                    continue
                if probe == dim.name or probe in dim.name or dim.name in probe:
                    out.append(self.issue(
                        f"object::{probe}",
                        f"对象名 '{probe}' 与维度 '{dim.name}' 撞车 —— "
                        f"'{dim.name}' 是对象下的会变化条件，不是独立验证主体"))
                    break
        return out


@register
class MethodAsDimension(Rule):
    id = "method_as_dimension"
    severity = "error"
    category = CATEGORY_ORTHOGONAL
    description = "维度名里含方法词 —— 方法应在 L5，维度只描述会变化的条件"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for dim in ctx.model.dimensions:
            kw = contains_keyword(f"{dim.id} {dim.name}", METHOD_KEYWORDS)
            if kw:
                code = method_code_for(kw)
                out.append(self.issue(
                    f"dimension::{dim.key}",
                    f"维度 '{dim.name}' 的名字里含方法词 '{kw}' —— "
                    f"'{kw}' 应作为 L5 方法 {code} 表达，维度只描述会变化的条件"))
        return out


@register
class CheckAsDimension(Rule):
    id = "check_as_dimension"
    severity = "error"
    category = CATEGORY_ORTHOGONAL
    description = "维度名里含检查词 —— 检查是 L6 属性，不是会变化的条件"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for dim in ctx.model.dimensions:
            kw = contains_keyword(f"{dim.id} {dim.name}", CHECK_KEYWORDS)
            if kw:
                out.append(self.issue(
                    f"dimension::{dim.key}",
                    f"维度 '{dim.name}' 的名字里含检查词 '{kw}' —— "
                    f"检查是 L6 属性，不是会变化的条件"))
        return out


@register
class FieldAsDimension(Rule):
    id = "field_as_dimension"
    severity = "error"
    category = CATEGORY_ORTHOGONAL
    description = "维度名以另一个维度的字段取值开头 —— 取值只该待在字段里"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        all_fields = ctx.model.all_fields
        for dim in ctx.model.dimensions:
            hits: List[Tuple[str, str]] = []
            for fld in all_fields:
                if fld.dim_key == dim.key:
                    continue
                for token in fld.cover_tokens():
                    if not token or _SHORT_RE.match(token):
                        continue        # 纯 ASCII 短 token（1/8/ld0）噪声太大
                    if dim.name.startswith(token) and dim.name != token:
                        hits.append((token, fld.name))
            if hits:
                token, fname = hits[0]
                out.append(self.issue(
                    f"dimension::{dim.key}",
                    f"维度名 '{dim.name}' 以字段 '{fname}' 的取值 '{token}' 开头 —— "
                    f"取值只该待在字段里。正确做法：维度用归类名"
                    f"（如 '{fname}'），取值回到字段 values"))
        return out


@register
class MethodTokenInValues(Rule):
    id = "method_token_in_field_values"
    severity = "warning"
    category = CATEGORY_ORTHOGONAL
    description = "字段取值与 L5 方法同名（文档十八节点名的正交性破坏）"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for fld in ctx.model.all_fields:
            for token in fld.cover_tokens():
                kw = contains_keyword(token, METHOD_KEYWORDS)
                if kw:
                    code = method_code_for(kw)
                    out.append(self.issue(
                        f"field::{fld.qualified}",
                        f"字段取值 '{token}' 与 L5 方法 {code} 同名 —— "
                        f"文档十八节点名的正交性破坏：同一个信息只能存在于一个层级。"
                        f"若 '{token}' 是要测的行为，请改成具体模式名；"
                        f"若要随机生成，用 method={code}"))
        return out


@register
class DuplicateFieldName(Rule):
    id = "duplicate_field_name"
    severity = "warning"
    category = CATEGORY_ORTHOGONAL
    description = "字段名在多个维度重复 —— 字段名是全局坐标，重复会让统计串味"

    def check(self, ctx: RuleContext) -> List[Issue]:
        all_fields = ctx.model.all_fields
        counts = Counter(f.name for f in all_fields)
        out: List[Issue] = []
        for name, n in counts.items():
            if n > 1:
                dims = "、".join(f.dim_key for f in all_fields if f.name == name)
                out.append(self.issue(
                    f"field::{name}",
                    f"字段名 '{name}' 在 {n} 个维度里重复（{dims}）—— "
                    f"字段名是全局坐标，重复会让关系表与覆盖统计产生歧义"))
        return out


@register
class DuplicateDimensionId(Rule):
    id = "duplicate_dimension_id"
    severity = "error"
    category = CATEGORY_ORTHOGONAL
    description = "维度 id 重复 —— 维度 id 是全局坐标，重复会让派生名字撞车"

    def check(self, ctx: RuleContext) -> List[Issue]:
        dims = list(ctx.model.dimensions)
        counts = Counter(d.key for d in dims)
        out: List[Issue] = []
        for key, n in counts.items():
            if n > 1:
                labels = "、".join(d.label for d in dims if d.key == key)
                out.append(self.issue(
                    f"dimension::{key}",
                    f"维度 id '{key}' 有 {n} 个（{labels}）—— "
                    f"维度 id 是全局坐标（`build_dimension` 拿它当 key）。"
                    f"同 id 的维度会让下游按 (维度, 取值) 展开出**重复测试点**，"
                    f"再撞成**同一个 SV 类名**（`attr_class_slug` 只看维度 + 取值）"
                    f"—— 编译期 Typedef 重定义，整轮回归跑不起来。"
                    f"多个接口落成同一维度时请**合成一个**（激励胜过响应）。"))
        return out


@register
class DuplicateFieldValue(Rule):
    id = "duplicate_field_value"
    severity = "warning"
    category = CATEGORY_ORTHOGONAL
    description = "同一字段内取值重复"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for fld in ctx.model.all_fields:
            dupes = [t for t, n in Counter(fld.cover_tokens()).items() if n > 1]
            if dupes:
                out.append(self.issue(f"field::{fld.qualified}",
                                      f"取值重复：{'、'.join(dupes)}"))
        return out


@register
class DimensionHasFields(Rule):
    id = "dimension_without_field"
    severity = "error"
    category = CATEGORY_ORTHOGONAL
    description = "维度没有任何字段，无法承载取值"

    def check(self, ctx: RuleContext) -> List[Issue]:
        return self.issues([
            (f"dimension::{dim.key}",
             f"维度 '{dim.label}' 没有任何字段，无法承载取值")
            for dim in ctx.model.dimensions if not dim.fields])


@register
class DimensionHasVariation(Rule):
    id = "dimension_without_variation"
    severity = "info"
    category = CATEGORY_ORTHOGONAL
    description = "维度只有一个取值点 —— 「会变化的条件」没有变化"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for dim in ctx.model.dimensions:
            if not dim.fields:
                continue
            if dim.value_point_count <= 1:
                out.append(self.issue(
                    f"dimension::{dim.key}",
                    f"维度 '{dim.label}' 只有 {dim.value_point_count} 个取值点 —— "
                    f"「会变化的条件」没有变化，可能不该单独作为维度"))
        return out


@register
class FieldHasValues(Rule):
    id = "field_without_values"
    severity = "warning"
    category = CATEGORY_ORTHOGONAL
    description = "字段没有任何取值点，覆盖率无法计算"

    def check(self, ctx: RuleContext) -> List[Issue]:
        return self.issues([
            (f"field::{fld.qualified}",
             f"字段 '{fld.name}'（{fld.type_name}）没有任何取值点，"
             f"覆盖率无法计算")
            for fld in ctx.model.all_fields if not fld.cover_tokens()])
