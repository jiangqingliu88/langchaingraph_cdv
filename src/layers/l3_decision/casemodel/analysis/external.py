"""外部真实 case 列表 ↔ 模型的反向核对。

前七组规则都是「模型对自己」——生成 case，再拿生成的 case 去量模型。
这一组换方向：拿**真实存在的 case 列表**去量模型，回答四个问题：

  1. 模型落后于实现了吗  真实 case 用了模型没声明的字段 / 取值 / 专题
  2. 实现落后于模型了吗  模型声明了、生成的 case 也覆盖了，但真实 case 没写
  3. 重复与命名          对象+子对象+字段取值相同即为重复（文档十二节）；
                        case_id 是否符合文档十五节
  4. 可复现吗            真实 case 有没有带环境指纹

**这里的结论不进模型完备性评分。** 评分必须只是模型的属性：若把「实现落后」
也算进去，同一个模型传两份完整度不同的 case 列表就会得到两个分数，
分数不再可复现 —— 与项目定位直接冲突。所以模型分一个数、真实覆盖另一个数。
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..domain import NO_NODE_CODE, CaseModel, ExternalCase
from ..generation import GenerationResult
from .coverage import (DimensionCoverage, FieldCoverage,
                       build_dimension_coverage, hits_from_cases, missing_pairs,
                       overall_ratio)
from .issues import CATEGORY_EXTERNAL, Issue

# 文档十五节：TC-<对象>-<子对象>-<方法>-<NN>
CASE_ID_RE = re.compile(r"^([A-Z][A-Z0-9]*)-([A-Z][A-Z0-9]*)-([A-Z][A-Z0-9]*)-"
                        r"([A-Z]+)-(\d{2,})$")


@dataclass
class ExternalReport:
    """真实 case 列表的核对结果。"""
    source: str = ""
    case_count: int = 0
    dimension_coverage: List[DimensionCoverage] = _field(default_factory=list)
    field_coverage: List[FieldCoverage] = _field(default_factory=list)
    generated_only: List[Tuple[str, str, str]] = _field(default_factory=list)
    duplicates: List[Tuple[str, List[str]]] = _field(default_factory=list)
    unknown_fields: List[Tuple[str, str]] = _field(default_factory=list)
    undeclared_values: List[Tuple[str, str, str]] = _field(default_factory=list)
    unknown_nodes: List[Tuple[str, str]] = _field(default_factory=list)
    unknown_themes: List[Tuple[str, str]] = _field(default_factory=list)
    unknown_methods: List[Tuple[str, str]] = _field(default_factory=list)
    invalid_ids: List[Tuple[str, str]] = _field(default_factory=list)
    cases_without_environment: int = 0
    cases_without_checks: int = 0
    node_coverage: Dict[str, int] = _field(default_factory=dict)
    theme_coverage: Dict[str, int] = _field(default_factory=dict)
    generated_ratio: float = 1.0
    issues: List[Issue] = _field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        return overall_ratio(self.dimension_coverage)

    @property
    def real_gap(self) -> List[Tuple[str, str, str]]:
        """真实缺口 = 模型生成了、但真实 case 没覆盖的取值。"""
        return list(self.generated_only)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "case_count": self.case_count,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "generated_ratio": round(self.generated_ratio, 4),
            "coverage": [
                {"dimension": d.name, "hit": d.hit_count, "total": d.total,
                 "ratio": round(d.ratio, 4),
                 "fields": [{"field": f.field, "type": f.field_type,
                             "hit": f.hit_count, "total": f.total,
                             "missing": f.missing, "derived": f.derived}
                            for f in d.fields]}
                for d in self.dimension_coverage],
            "generated_only": [{"dimension": d, "field": f, "value": v}
                               for d, f, v in self.generated_only],
            "duplicates": [{"fingerprint": fp, "case_ids": ids}
                           for fp, ids in self.duplicates],
            "unknown_fields": [{"case_id": c, "field": f}
                               for c, f in self.unknown_fields],
            "undeclared_values": [{"case_id": c, "field": f, "value": v}
                                  for c, f, v in self.undeclared_values],
            "unknown_nodes": [{"case_id": c, "node": n} for c, n in self.unknown_nodes],
            "unknown_themes": [{"case_id": c, "theme": t} for c, t in self.unknown_themes],
            "unknown_methods": [{"case_id": c, "method": m}
                                for c, m in self.unknown_methods],
            "invalid_ids": [{"case_id": c, "reason": r} for c, r in self.invalid_ids],
            "cases_without_environment": self.cases_without_environment,
            "cases_without_checks": self.cases_without_checks,
            "node_coverage": dict(self.node_coverage),
            "theme_coverage": dict(self.theme_coverage),
            "issues": [{"severity": i.severity, "category": i.category,
                        "rule": i.rule, "target": i.target, "message": i.message}
                       for i in self.issues],
        }


def _describe_fingerprint(fp: Tuple[str, str, Tuple[Tuple[str, str], ...]]) -> str:
    obj, sub, fields = fp
    parts = "、".join(f"{k}={v}" for k, v in fields) or "（无字段）"
    return f"{obj} / {sub or '（无节点）'} / {parts}"


def cross_check(model: CaseModel, cases: Sequence[ExternalCase],
                generated: Optional[GenerationResult] = None,
                source: str = "") -> ExternalReport:
    """拿真实 case 列表核对模型。"""
    report = ExternalReport(source=source, case_count=len(cases))
    issues: List[Issue] = []

    field_by_name = {f.name: f for f in model.all_fields}
    declared_tokens = {f.name: set(f.cover_tokens()) for f in model.all_fields}
    # 节点的 id 与代号是两件事：id 是机器索引（外形表 sub_object_id），
    # 代号只出现在 case_id 里。混用会让「按节点统计」全查不中。
    node_ids = {n.id for n in model.tree_nodes}
    node_codes = {n.code for n in model.tree_nodes}
    theme_ids = {t.id for t in model.themes}

    def add(rule: str, severity: str, target: str, message: str) -> None:
        issues.append(Issue(severity, rule, target, message, CATEGORY_EXTERNAL))

    for case in cases:
        if not case.fields:
            add("external_case_without_fields", "warning", f"case::{case.label}",
                f"真实 case {case.label} 没有任何字段取值，无法参与覆盖统计")

        for name, token in case.fields.items():
            if name not in field_by_name:
                report.unknown_fields.append((case.label, name))
                add("external_unknown_field", "error", f"case::{case.label}",
                    f"真实 case 用了模型未声明的字段 '{name}' —— "
                    f"模型落后于实现，请先在 dimensions 里补上这个字段")
                continue
            if token and token not in declared_tokens.get(name, set()):
                report.undeclared_values.append((case.label, name, token))
                declared = "、".join(sorted(declared_tokens.get(name, set()))) or "空"
                add("external_undeclared_value", "error", f"case::{case.label}",
                    f"取值 '{name}={token}' 不在模型声明的取值表里"
                    f"（已声明：{declared}）—— 要么补进 values，要么该 case 写错了")

        if case.sub_object_id and model.tree_nodes:
            if case.sub_object_id not in node_ids:
                report.unknown_nodes.append((case.label, case.sub_object_id))
                add("external_unknown_node", "error", f"case::{case.label}",
                    f"组织树节点 '{case.sub_object_id}' 不在模型里")

        if case.theme and theme_ids and case.theme not in theme_ids:
            report.unknown_themes.append((case.label, case.theme))
            add("external_unknown_theme", "error", f"case::{case.label}",
                f"专题 '{case.theme}' 不在模型里 —— 要么模型落后，要么写错了")

        if case.method and model.methods and case.method not in model.methods:
            report.unknown_methods.append((case.label, case.method))
            add("external_unknown_method", "warning", f"case::{case.label}",
                f"方法 '{case.method}' 不在模型声明的 methods 里"
                f"（{'、'.join(model.methods)}）")

        m = CASE_ID_RE.match(case.case_id)
        if not m:
            report.invalid_ids.append(
                (case.case_id, "不符合 TC-<对象>-<子对象>-<方法>-<NN>"))
            add("external_case_id_pattern", "warning", f"case::{case.label}",
                f"case_id '{case.case_id}' 不符合文档十五节的命名约定 "
                f"TC-<对象>-<子对象>-<方法>-<NN>")
        else:
            # TC-<对象>-<节点>-<方法>-<NN> → 5 组：对象 / 节点 / 方法 / 序号
            _tc, obj_code, node_code, method_code, _nn = m.groups()
            if obj_code != model.object_code:
                add("external_case_id_object_mismatch", "info", f"case::{case.label}",
                    f"case_id 里的对象代号 '{obj_code}' 与模型的 "
                    f"'{model.object_code}' 不一致")
            if model.tree_nodes and node_code not in node_codes \
                    and node_code != NO_NODE_CODE:
                add("external_case_id_node_mismatch", "info", f"case::{case.label}",
                    f"case_id 里的节点代号 '{node_code}' 不在组织树里"
                    f"（{'、'.join(sorted(node_codes))}）")
            if model.methods and method_code not in model.methods:
                add("external_case_id_method_mismatch", "info", f"case::{case.label}",
                    f"case_id 里的方法代号 '{method_code}' 不在模型的 methods 里")

        if not case.environment:
            report.cases_without_environment += 1
        if not case.checks:
            report.cases_without_checks += 1

    if report.cases_without_environment:
        add("external_case_missing_environment", "error", "case_list",
            f"{report.cases_without_environment}/{len(cases)} 个真实 case "
            f"没有环境指纹，失败后无法复现")
    if report.cases_without_checks:
        add("external_case_missing_checks", "warning", "case_list",
            f"{report.cases_without_checks}/{len(cases)} 个真实 case "
            f"没有挂任何检查项")

    # ── 重复（文档十二节）──
    buckets: Dict[Tuple, List[str]] = defaultdict(list)
    for case in cases:
        buckets[case.fingerprint()].append(case.label)
    report.duplicates = [(_describe_fingerprint(fp), ids)
                         for fp, ids in buckets.items() if len(ids) > 1]
    for desc, ids in report.duplicates:
        add("external_duplicate_case", "warning", f"duplicate::{desc}",
            f"{len(ids)} 个 case 的对象+子对象+字段取值完全相同，"
            f"只是方法或名字不同（{'、'.join(ids)}）—— 文档十二节：这就是重复")

    # ── 真实覆盖 ──
    hits = hits_from_cases(cases)
    dim_cov, field_cov = build_dimension_coverage(model.dimensions, hits)
    report.dimension_coverage = dim_cov
    report.field_coverage = field_cov

    for case in cases:
        if case.sub_object_id:
            report.node_coverage[case.sub_object_id] = \
                report.node_coverage.get(case.sub_object_id, 0) + 1
        if case.theme:
            report.theme_coverage[case.theme] = \
                report.theme_coverage.get(case.theme, 0) + 1

    # 模型有、真实没有的节点 / 专题 —— 实现漏了哪块结构、哪一轮
    for node in model.leaf_nodes:
        if node.id not in report.node_coverage:
            add("external_node_uncovered", "warning", f"org_leaf::{node.id}",
                f"组织树叶子 '{node.path_label()}'（{node.code}）在真实 case 里"
                f"一个都没有 —— 这块结构的实现还没跟上")
    for theme in model.themes:
        if theme.id not in report.theme_coverage:
            add("external_theme_uncovered", "warning", f"theme::{theme.key}",
                f"专题 '{theme.label}'（{theme.priority}）在真实 case 里一个都没有 —— "
                f"这一轮还没落地")

    # ── 真实缺口：模型生成了、真实 case 没写 ──
    if generated is not None:
        gen_hits = hits_from_cases(generated.cases)
        report.generated_ratio = overall_ratio(
            build_dimension_coverage(model.dimensions, gen_hits)[0])

        for dim_name, fname, token in missing_pairs(dim_cov):
            if token in gen_hits.get(fname, set()):
                report.generated_only.append((dim_name, fname, token))
        for dim_name, fname, token in report.generated_only:
            add("external_coverage_gap", "warning", f"gap::{fname}",
                f"维度 '{dim_name}' 的 '{fname}={token}' 已被模型生成的 case 覆盖，"
                f"但真实 case 列表里没有 —— 实现落后于模型")

    report.issues = issues
    return report
