"""Agent 接入面的公共实现。

设计模式：**Adapter**。三个接入面（LangChain @tool / 声明式 ToolRegistry /
ToolHub 的 ITool）需要的都是同一件事：吃一段 YAML 文本、吐一个 JSON dict。
差别只在包装方式，不在语义。所以语义集中在这里，三处都调它 ——
否则同一个问题在三个面上给出不同答案，排查起来是灾难。

返回值一律是 **dict**（不是 JSON 字符串）：需要字符串的接入面自己 json.dumps，
需要结构化数据的接入面直接用。这样两边都不用解析自己刚序列化的东西。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml

from ..analysis import analyze
from ..analysis.issues import count_by_severity
from ..analysis.schema_check import SchemaChecker
from ..domain import CaseModelError
from ..domain.errors import CaseListError
from ..generation import generate
from ..repository import load_model_from_text
from ..repository.case_list import cases_from_text

# 工具名 —— 三个接入面共用同一批名字，便于互相印证
TOOL_VALIDATE = "casemodel_validate"
TOOL_GAPS = "casemodel_gaps"
TOOL_GENERATE = "casemodel_generate"
TOOL_NAMES = (TOOL_VALIDATE, TOOL_GAPS, TOOL_GENERATE)


def _issue_dicts(issues) -> List[Dict[str, str]]:
    return [{"severity": i.severity, "category": i.category, "rule": i.rule,
             "target": i.target, "message": i.message} for i in issues]


# ════════════════════════════════════════════════════════════
# casemodel_validate
# ════════════════════════════════════════════════════════════

def run_validate(yaml_text: str) -> Dict[str, Any]:
    """YAML 文本 → JSON Schema 校验结果。"""
    if not isinstance(yaml_text, str) or not yaml_text.strip():
        return {"valid": False, "error_count": 1, "warning_count": 0,
                "issues": [{"severity": "error", "category": "schema",
                            "rule": "empty_input", "target": "<root>",
                            "message": "yaml_text 为空"}]}
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return {"valid": False, "error_count": 1, "warning_count": 0,
                "issues": [{"severity": "error", "category": "schema",
                            "rule": "yaml_parse_error", "target": "<root>",
                            "message": f"YAML 解析失败: {exc}"}]}

    from pathlib import Path
    issues = SchemaChecker().check_data(data, Path("<inline>"))
    counts = count_by_severity(issues)
    return {
        "valid": counts["error"] == 0,
        "error_count": counts["error"],
        "warning_count": counts["warning"],
        "issues": _issue_dicts(issues),
    }


# ════════════════════════════════════════════════════════════
# casemodel_gaps
# ════════════════════════════════════════════════════════════

def run_gaps(yaml_text: str, max_cases: Optional[int] = None,
             cases_text: Optional[str] = None) -> Dict[str, Any]:
    """YAML 文本 → 完备性分析。cases_text 给出时追加反向核对。"""
    try:
        model = load_model_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    external = None
    if cases_text:
        try:
            external = cases_from_text(cases_text, hint=".yaml", source="<inline>")
        except CaseListError as exc:
            return {"error": f"外部 case 列表解析失败: {exc}"}

    result = analyze(model, max_cases=max_cases, external=external,
                     external_source="<inline>" if external else "")
    payload: Dict[str, Any] = {
        "object": model.object,
        "object_cn": model.object_cn,
        "score": round(result.score.total, 1),
        "score_breakdown": {name: {"sub": round(sub, 4),
                                   "weighted": round(weighted, 2)}
                            for name, sub, weighted in result.score.rows()},
        "summary": result.summary(),
        "org_tree": result.node_rows(),
        "themes": result.theme_rows(),
        "coverage": [
            {"dimension": d.name, "hit": d.hit_count, "total": d.total,
             "ratio": round(d.ratio, 4),
             "missing": {f.field: f.missing for f in d.fields if f.missing}}
            for d in result.dimension_coverage],
        "issues": _issue_dicts(result.issues),
    }
    if result.external is not None:
        payload["external"] = result.external.to_dict()
    return payload


# ════════════════════════════════════════════════════════════
# casemodel_generate
# ════════════════════════════════════════════════════════════

def run_generate(yaml_text: str, max_cases: Optional[int] = None,
                 seed: Optional[int] = None) -> Dict[str, Any]:
    """YAML 文本 → case 属性表。"""
    try:
        model = load_model_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    result = generate(model, seed=seed, max_cases=max_cases)
    return {
        "count": result.count,
        "seed": result.seed,
        "driver": result.driver,
        "truncated": result.truncated,
        "dropped": result.dropped,
        "themes_used": result.themes_used,
        "priorities_used": result.priorities_used,
        "methods_used": result.methods_used,
        "notes": result.notes,
        "cases": [c.to_dict() for c in result.cases],
    }


RUNNERS = {
    TOOL_VALIDATE: run_validate,
    TOOL_GAPS: run_gaps,
    TOOL_GENERATE: run_generate,
}
