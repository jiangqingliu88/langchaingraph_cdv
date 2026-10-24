"""分析层 —— 只读地判断「模型是否完备」，不改模型、不造 case。

设计模式：
    Specification   每条校验规则一个自包含单元，可插拔（rules/ 下按分类分模块）
    Facade          analyze() 一个入口串起全部步骤
    Strategy        评分项各自独立、权重集中可审计（score.py）

对外只从这里取名字。规则清单从 specifications.load_rules() 读 ——
报告、GUI、规则文档三处共用一份，不会漂移。
"""
from __future__ import annotations

from .coverage import (DimensionCoverage, FieldCoverage,
                       build_dimension_coverage, hits_from_cases,
                       missing_pairs, overall_ratio)
from .external import ExternalReport, cross_check
from .facade import analyze, analyze_file, analyze_text
from .issues import (CATEGORY_COVERAGE, CATEGORY_CROSS, CATEGORY_ENVIRONMENT,
                     CATEGORY_EXTERNAL, CATEGORY_NAMES, CATEGORY_ORDER,
                     CATEGORY_ORG_TREE, CATEGORY_ORTHOGONAL, CATEGORY_REFERENCE,
                     CATEGORY_SCHEMA, CATEGORY_THEME, Issue, category_rank,
                     count_by_severity, group_by_category, sort_issues)
from .matrix import CrossMatrix, MatrixCell, build_matrix
from .result import AnalysisResult
from .schema_check import SchemaChecker, collect_yaml_paths, load_schema
from .score import SCORE_NAMES, SCORE_WEIGHTS, ScoreBreakdown, compute_score
from .specifications import (Rule, RuleContext, load_rules, register,
                             rule_docs, rule_ids)

__all__ = [
    # 门面
    "analyze", "analyze_file", "analyze_text", "AnalysisResult",
    # 规则基础设施
    "Rule", "RuleContext", "register", "load_rules", "rule_ids", "rule_docs",
    # 诊断
    "Issue", "sort_issues", "count_by_severity", "group_by_category",
    "category_rank", "CATEGORY_NAMES", "CATEGORY_ORDER",
    "CATEGORY_SCHEMA", "CATEGORY_REFERENCE", "CATEGORY_ORTHOGONAL",
    "CATEGORY_ORG_TREE", "CATEGORY_THEME", "CATEGORY_CROSS",
    "CATEGORY_COVERAGE", "CATEGORY_ENVIRONMENT", "CATEGORY_EXTERNAL",
    # 产物
    "CrossMatrix", "MatrixCell", "build_matrix",
    "DimensionCoverage", "FieldCoverage", "build_dimension_coverage",
    "hits_from_cases", "missing_pairs", "overall_ratio",
    "ExternalReport", "cross_check",
    "ScoreBreakdown", "compute_score", "SCORE_WEIGHTS", "SCORE_NAMES",
    # schema 门禁（归在 analysis：它产出的是诊断）
    "SchemaChecker", "collect_yaml_paths", "load_schema",
]
