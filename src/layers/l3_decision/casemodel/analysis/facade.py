"""analyze() —— 分析的门面。

设计模式：**Facade**。调用方（CLI / GUI / Agent 适配器）只需要记住一个函数：

    result = analyze(model)                      # 纯模型自检
    result = analyze(model, external=cases)      # 追加「模型 vs 实现」核对

门面负责把它们按固定顺序串起来，顺序本身是有讲究的：

    1. 生成 case            —— 一切覆盖统计的分母
    2. 建交叉矩阵           —— 规则（专题互斥）要用
    3. 建覆盖结构           —— 规则要用
    4. 建节点/专题命中表     —— 规则要用
    5. 跑全部规则           —— 只读上下文
    6. 算分                 —— **只吃模型自身的诊断**
    7. 外部核对             —— 结果与模型诊断分开保存
    8. 组装 AnalysisResult

第 6 步和第 7 步的顺序是刻意的：外部核对的 Issue 不进评分，
只进 issues（报告与退出码），这样分数才是模型的属性、可复现。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..domain import CaseModel, ExternalCase
from ..generation import GenerationResult, generate, theme_estimates
from .coverage import build_dimension_coverage, hits_from_cases
from .external import ExternalReport, cross_check
from .issues import Issue, sort_issues
from .matrix import build_matrix
from .result import AnalysisResult
from .score import compute_score
from .specifications import RuleContext, load_rules


def analyze(model: CaseModel, *, generation: Optional[GenerationResult] = None,
            seed: Optional[int] = None, max_cases: Optional[int] = None,
            external: Optional[Sequence[ExternalCase]] = None,
            external_source: str = "") -> AnalysisResult:
    """对模型做全量完备性分析。

    generation 可传入以复用已生成的 case；external 传入外部真实 case 列表
    （domain.ExternalCase）以追加反向核对。两者都省略时等价于纯模型自检。
    """
    gen_result = generation if generation is not None else generate(
        model, seed=seed, max_cases=max_cases)

    matrix = build_matrix(model)

    hits = hits_from_cases(gen_result.cases)
    dim_cov, field_cov = build_dimension_coverage(model.dimensions, hits)

    node_hits: Dict[str, List[Any]] = {}
    theme_hits: Dict[str, List[Any]] = {}
    for case in gen_result.cases:
        node_hits.setdefault(case.node_key, []).append(case)
        if case.theme:
            theme_hits.setdefault(case.theme, []).append(case)

    ctx = RuleContext(model=model, generation=gen_result, matrix=matrix,
                      dimension_coverage=dim_cov, field_coverage=field_cov,
                      node_hits=node_hits, theme_hits=theme_hits)

    model_issues: List[Issue] = []
    for rule in load_rules():
        model_issues.extend(rule.check(ctx))
    model_issues = sort_issues(model_issues)

    # 评分只吃模型自身的诊断 —— 外部核对的缺陷不进分数（见模块头）
    score = compute_score(ctx, model_issues)

    external_report: Optional[ExternalReport] = None
    if external is not None:
        external_report = cross_check(model, external, gen_result,
                                      source=external_source)

    all_issues = sort_issues(
        model_issues + (external_report.issues if external_report else []))

    return AnalysisResult(
        model=model,
        generation=gen_result,
        issues=all_issues,
        model_issues=model_issues,
        matrix=matrix,
        dimension_coverage=dim_cov,
        field_coverage=field_cov,
        score=score,
        explosion=theme_estimates(model),
        external=external_report,
    )


def analyze_file(path: str, *, cases: Optional[str] = None,
                 **kwargs: Any) -> AnalysisResult:
    """从 YAML 文件分析；cases 给出外部真实 case 列表路径。

    清单里写 `tests:` 列了多个被测对象时也走这里 —— 合并语义见 `multi.py`。
    """
    # multi 反过来要 import 本模块的 analyze —— 放函数体里避开循环 import
    from ..repository import load_models
    from .multi import analyze_many
    if cases:
        from ..repository.case_list import load_cases
        kwargs.setdefault("external", load_cases(cases))
        kwargs.setdefault("external_source", str(cases))
    return analyze_many(load_models(path), **kwargs)


def analyze_text(text: str, *, source: str = "<text>",
                 cases: Optional[str] = None,
                 **kwargs: Any) -> AnalysisResult:
    """从 YAML 文本分析；cases 给出外部真实 case 列表路径。

    与 analyze_file 对称，但吃的是文本不是路径 —— 编辑器靠它分析「尚未保存的
    改动」，不必先写盘。
    """
    from ..repository import load_models_from_text
    from .multi import analyze_many
    if cases:
        from ..repository.case_list import load_cases
        kwargs.setdefault("external", load_cases(cases))
        kwargs.setdefault("external_source", str(cases))
    return analyze_many(load_models_from_text(text, source=source), **kwargs)

