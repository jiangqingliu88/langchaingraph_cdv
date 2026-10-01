"""取值覆盖 —— 文档十二节：流控维度覆盖率 = 各字段取值命中数 / 总取值。

分母是字段声明的取值点，分子是被 case 命中的那些。这一组只负责把缺口
说清楚（缺哪些取值、在哪个维度），以及报出「统计本身没法做」的情况
（字段名重复、一个 case 都没生成）。
"""
from __future__ import annotations

from collections import Counter
from typing import List

from ..issues import CATEGORY_COVERAGE, Issue
from ..specifications import Rule, RuleContext, register


@register
class FieldValueCovered(Rule):
    id = "field_value_uncovered"
    severity = "warning"
    category = CATEGORY_COVERAGE
    description = "维度的取值点没有被全部覆盖"

    def check(self, ctx: RuleContext) -> List[Issue]:
        out: List[Issue] = []
        for dcov in ctx.dimension_coverage:
            if dcov.total and dcov.hit_count < dcov.total:
                missing = "、".join(f"{f} 缺 {','.join(m)}"
                                    for f, m in dcov.missing if m)
                out.append(self.issue(
                    f"dimension::{dcov.key}",
                    f"维度 '{dcov.name}' 取值覆盖 {dcov.hit_count}/{dcov.total}"
                    f"（{dcov.ratio:.0%}）：{missing}"))
        return out


@register
class CoverageAmbiguousField(Rule):
    id = "coverage_ambiguous_field"
    severity = "warning"
    category = CATEGORY_COVERAGE
    description = "字段名重复导致覆盖统计无法区分维度"

    def check(self, ctx: RuleContext) -> List[Issue]:
        counts = Counter(f.name for f in ctx.model.all_fields)
        out: List[Issue] = []
        for name, n in counts.items():
            if n > 1:
                flds = [f for f in ctx.model.all_fields if f.name == name]
                out.append(self.issue(
                    f"field::{name}",
                    f"字段名 '{name}' 在多个维度重复，覆盖统计无法区分是哪一维的取值"
                    f"（{' / '.join(f.qualified for f in flds)}）"))
        return out


@register
class CasesGenerated(Rule):
    id = "no_cases_generated"
    severity = "error"
    category = CATEGORY_COVERAGE
    description = "一个 case 都没生成，取值覆盖率全部为 0"

    def check(self, ctx: RuleContext) -> List[Issue]:
        if ctx.generation.count:
            return []
        return [self.issue(
            "generation",
            "没有生成任何 case —— 检查 themes / cross_groups 的维度与取值是否为空，"
            "以及 generation.priorities 是不是把所有专题都排除了")]


@register
class GenerationNotes(Rule):
    id = "generation_note"
    severity = "warning"
    category = CATEGORY_COVERAGE
    description = "生成过程中的注意事项（截断、互斥剔除等）"

    def check(self, ctx: RuleContext) -> List[Issue]:
        return self.issues([("generation", note)
                            for note in ctx.generation.notes])
