"""取值覆盖 —— 文档十二节：流控维度覆盖率 = 各字段取值命中数 / 总取值。

分母是字段声明的取值点，分子是被 case 命中的那些。这一组只负责把缺口
说清楚（缺哪些取值、在哪个维度），以及报出「统计本身没法做」的情况
（字段名重复、一个 case 都没生成）。
"""
from __future__ import annotations

from collections import Counter
from typing import Any, List

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


@register
class CoverBinUnreachable(Rule):
    id = "cover_bin_unreachable"
    severity = "error"
    category = CATEGORY_COVERAGE
    description = "声明的覆盖仓没有任何取值点能打到 —— 覆盖率封顶"

    def check(self, ctx: RuleContext) -> List[Issue]:
        """显式覆盖仓 vs 取值点：**有没有哪个仓是空的**。

        ## 为什么这条必须在建模期报

        字段可以给**显式覆盖仓**（`cover_bins` 的对象形式）—— 那是"值域的一个划分"，
        `queue_level` 的 0-32 分六档就是。此时**取值点与 bin 不是一比一**：用例生成
        仍按取值点走（一个取值点一条 test），而覆盖率按 bin 收。多对一是正常的。

        **但"某个 bin 一个取值点都打不到"不是多对一，是空洞。** 后果是声明的覆盖率
        **永远封顶**（N 个 bin 里有一个空的，就上不去 100%），而**没有任何环节会报错**：

          · covergroup 编译通过（`bins c1 = {1};` 语法没问题）
          · 回归跑得过（跑的是取值点，与 bin 无关）
          · 只是那个数字怎么跑都到不了

        实测踩过一次：`cluster_id` 写了 4 个显式仓（c0..c3）却**没给 `boundary`**
        —— `RangeField` 退化到 `[min, max]` 两个端点，于是 c1/c2 永远打不到，
        覆盖率封顶 50%，而模型、covergroup、日志看上去全都正常。

        ## 判据

        逐个 bin 看它覆盖的取值区间里**有没有 `value_points()` 里的点**。
        区间仓 `{[1:7]}` 是「落在区间内」；单值/集合仓比相等。
        """
        out: List[Issue] = []
        for dim in ctx.model.dimensions:
            for fld in dim.fields:
                explicit = [b for b in (fld.cover_bins or [])
                            if isinstance(b, dict)]
                if not explicit:
                    continue                    # 没写显式仓 —— 取值点与 bin 天然一比一
                pts = [p.token for p in fld.value_points()]
                nums = [int(t) for t in pts
                        if str(t).strip().lstrip("-").isdigit()]
                if not pts:
                    out.append(self.issue(
                        f"field::{fld.qualified}",
                        f"字段 '{fld.name}' 声明了 {len(explicit)} 个显式覆盖仓，"
                        f"但**一个取值点都没有** —— 用例生成侧产不出 test，"
                        f"这些仓永远打不到"))
                    continue
                empty = [b.get("name") for b in explicit
                         if not _bin_hits(b, nums, pts)]
                if empty:
                    out.append(self.issue(
                        f"field::{fld.qualified}",
                        f"字段 '{fld.name}' 有 {len(empty)} 个覆盖仓**没有任何取值点"
                        f"能打到**：{'、'.join(str(e) for e in empty)} —— "
                        f"声明的覆盖率永远封顶。用例是按 `value_points()` 生成的"
                        f"（当前 {len(pts)} 个：{'、'.join(pts[:8])}"
                        f"{'…' if len(pts) > 8 else ''}），"
                        f"而覆盖率按这些仓收。给字段补 `boundary` / `values`，"
                        f"让每个仓至少有一个取值点落进去"))
        return out


def _bin_hits(bin_spec: dict, nums: List[int], tokens: List[str]) -> bool:
    """这个仓的区间/取值里，有没有 `value_points()` 里的点。"""
    at = bin_spec.get("at")
    if at is not None:
        return str(at) in tokens or at in nums
    vals = bin_spec.get("values")
    if isinstance(vals, (list, tuple)):
        return any(v in nums or str(v) in tokens for v in vals)
    lo = hi = None
    rng = bin_spec.get("range")
    if isinstance(rng, (list, tuple)) and rng:
        lo = rng[0]
        hi = rng[1] if len(rng) > 1 else None
    elif bin_spec.get("from") is not None:
        lo, hi = bin_spec.get("from"), bin_spec.get("to")
    if lo is None:
        return False
    try:
        lo_i = int(lo)
        hi_i = int(hi) if hi is not None else 1 << 62
    except (TypeError, ValueError):
        return False
    return any(lo_i <= v <= hi_i for v in nums)


@register
class ValuePointUnmapped(Rule):
    id = "value_point_unmapped"
    severity = "error"
    category = CATEGORY_COVERAGE
    description = "取值点不在任何合法覆盖仓里 —— 用例会跑，但覆盖率不记这一笔"

    def check(self, ctx: RuleContext) -> List[Issue]:
        """`cover_bin_unreachable` 的反向检查：**每个取值点都得有归属**。

        正向检查回答"仓空不空"，反向回答"点了没有仓收"。后者漏掉时的表现是：
        用例照常生成、仿真照常跑、日志全绿，而那个取值**不贡献任何覆盖率** ——
        看上去像"这个点不重要"，实际是建模时漏了一个仓。
        """
        out: List[Issue] = []
        for dim in ctx.model.dimensions:
            for fld in dim.fields:
                explicit = [b for b in (fld.cover_bins or [])
                            if isinstance(b, dict)]
                if not explicit:
                    continue
                lost = [p.token for p in fld.value_points()
                        if not any(_bin_hits_value(b, p.token) for b in explicit)]
                if lost:
                    out.append(self.issue(
                        f"field::{fld.qualified}",
                        f"字段 '{fld.name}' 有 {len(lost)} 个取值点**不在任何覆盖仓里**："
                        f"{'、'.join(lost[:8])}{'…' if len(lost) > 8 else ''} —— "
                        f"这些取值点会生成 test，但覆盖率不记它们（建模漏了仓）"))
        return out


@register
class CoverBinOverlap(Rule):
    id = "cover_bin_overlap"
    severity = "warning"
    category = CATEGORY_COVERAGE
    description = "显式覆盖仓之间取值重叠 —— 同一个值会被记进多个仓"

    def check(self, ctx: RuleContext) -> List[Issue]:
        """仓重叠会让"命中率"虚高（一个值记两笔）。

        分区式的仓（`{[0:7]}` / `{[8:15]}`）不该重叠；真要重叠（分维度口径不同）
        就该在模型里写清楚，而不是让它悄悄发生。
        """
        out: List[Issue] = []
        for dim in ctx.model.dimensions:
            for fld in dim.fields:
                explicit = [b for b in (fld.cover_bins or [])
                            if isinstance(b, dict)]
                for i in range(len(explicit)):
                    for j in range(i + 1, len(explicit)):
                        if _bins_overlap(explicit[i], explicit[j]):
                            out.append(self.issue(
                                f"field::{fld.qualified}",
                                f"字段 '{fld.name}' 的覆盖仓 "
                                f"'{explicit[i].get('name')}' 与 "
                                f"'{explicit[j].get('name')}' 取值重叠 —— "
                                f"同一个值会同时记进两个仓"))
        return out


def _bin_hits_value(bin_spec: dict, token: str) -> bool:
    """单个取值点能不能落进这个仓（数值按区间比，文本按 `at`/`values` 比）。"""
    try:
        num = int(str(token).strip())
    except (TypeError, ValueError):
        num = None
    return _bin_hits(bin_spec, [num] if num is not None else [], [str(token)])


def _bin_shape(bin_spec: dict) -> tuple:
    """仓 → (文本点集, 数值点集, 数值闭区间)。"""
    points = set()
    nums = set()
    at = bin_spec.get("at")
    if at is not None:
        points.add(str(at))
        _add_int(nums, at)
    vals = bin_spec.get("values")
    if isinstance(vals, (list, tuple)):
        for value in vals:
            points.add(str(value))
            _add_int(nums, value)
    span = None
    rng = bin_spec.get("range")
    if isinstance(rng, (list, tuple)) and rng:
        span = (rng[0], rng[1] if len(rng) > 1 else rng[0])
    elif bin_spec.get("from") is not None:
        span = (bin_spec.get("from"), bin_spec.get("to"))
    if span is not None:
        try:
            lo = int(span[0])
            hi = int(span[1]) if span[1] is not None else lo
            span = (lo, hi)
        except (TypeError, ValueError):
            span = None
    return points, nums, span


def _add_int(target: set, value: Any) -> None:
    try:
        target.add(int(str(value).strip()))
    except (TypeError, ValueError):
        return


def _bins_overlap(a: dict, b: dict) -> bool:
    pa, na, sa = _bin_shape(a)
    pb, nb, sb = _bin_shape(b)
    if pa & pb or na & nb:
        return True
    if sa and sb:
        return not (sa[1] < sb[0] or sb[1] < sa[0])
    if sa and nb:
        return any(sa[0] <= v <= sa[1] for v in nb)
    if sb and na:
        return any(sb[0] <= v <= sb[1] for v in na)
    return False
