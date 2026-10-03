"""工具的程序化接口 —— 吃 YAML 文本、吐 dict。

三个函数覆盖这个工具的全部能力，**零 LLM 依赖**（不 import langchain /
ToolHub）：任何 Python 调用方、脚本、或 Agent 适配器都可以直接用。

    run_validate(yaml_text)                     → JSON Schema 校验结果
    run_gaps(yaml_text, max_cases, cases_text)  → 完备性分析（可选反向核对）
    run_generate(yaml_text, max_cases, seed)    → case 属性表

CLI（cli.py）与 Agent 适配器（src/agents/verify/casemodel/）都走这里 ——
语义只此一份，包装各写各的。这也是「工具目录保持纯净」的落点：
本包不含任何面向 LLM 的代码。

返回值一律是 **dict**（不是 JSON 字符串）：需要字符串的调用方自己 json.dumps，
需要结构化数据的直接用 —— 两边都不用解析自己刚序列化的东西。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .analysis import analyze
from .analysis.multi import analyze_many, generate_many
from .analysis.issues import count_by_severity
from .analysis.schema_check import SchemaChecker
from .domain import CaseModelError
from .domain.errors import CaseListError
from .repository import load_model_from_text, load_models_from_text
from .repository.case_list import cases_from_text

# 工具名 —— CLI、Agent 适配器、schema.yaml 三处共用同一批名字
TOOL_VALIDATE = "casemodel_validate"
TOOL_GAPS = "casemodel_gaps"
TOOL_GENERATE = "casemodel_generate"
#: 把属性取值摊平成 UVM 能吃的 tests 片段（**一条 = 一个 UVM_TEST**）。
#: 产物是**文本契约**，本工具不 import uvm_tools —— 见 `run_uvm_tests`
TOOL_UVM_TESTS = "casemodel_uvm_tests"

#: 三面（LangChain / ToolRegistry / ToolHub）共用的名单。
#: **`run_uvm_tests` 暂时不在里面**：进这个名单就得在 `src/agents/verify/casemodel/`
#: 的 `tool_specs()` 与 langchain 包装里各补一份，否则 `build_casemodel_tools()`
#: 会在 `classes[name]` 上 KeyError（踩过）。它是给人用的（`cli uvm-tests` /
#: `api.run_uvm_tests`），不是给 Agent 用的 —— 要接进 Agent 时再把它加进来，
#: 并同时补另外两面。
TOOL_NAMES = (TOOL_VALIDATE, TOOL_GAPS, TOOL_GENERATE)


def _issue_dicts(issues) -> List[Dict[str, str]]:
    return [{"severity": i.severity, "category": i.category, "rule": i.rule,
             "target": i.target, "message": i.message} for i in issues]


# ════════════════════════════════════════════════════════════
# validate
# ════════════════════════════════════════════════════════════

def run_validate(yaml_text: str) -> Dict[str, Any]:
    """YAML 文本 → JSON Schema 校验结果。

    只回答「文档写对了吗」；引用是否存在、层级是否错位由 run_gaps 回答。
    """
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

    issues = SchemaChecker().check_data(data, Path("<inline>"))
    counts = count_by_severity(issues)
    return {
        "valid": counts["error"] == 0,
        "error_count": counts["error"],
        "warning_count": counts["warning"],
        "issues": _issue_dicts(issues),
    }


# ════════════════════════════════════════════════════════════
# gaps
# ════════════════════════════════════════════════════════════

def run_gaps(yaml_text: str, max_cases: Optional[int] = None,
             cases_text: Optional[str] = None) -> Dict[str, Any]:
    """YAML 文本 → 全量完备性分析。

    cases_text 给出时追加「模型 vs 实现」反向核对 —— 注意外部核对的缺陷
    不进模型评分（评分必须只是模型的属性，否则换一份 case 列表分数就变）。
    """
    try:
        models = load_models_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    external = None
    if cases_text:
        try:
            external = cases_from_text(cases_text, hint=".yaml", source="<inline>")
        except CaseListError as exc:
            return {"error": f"外部 case 列表解析失败: {exc}"}

    # 单对象时它就是 analyze()；多对象时按「一套评分 + 每对象一棵树」合并
    result = analyze_many(models, max_cases=max_cases, external=external,
                          external_source="<inline>" if external else "")
    payload: Dict[str, Any] = {
        "object": result.model.object,
        "object_cn": result.model.object_cn,
        "object_count": len(models),
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
# generate
# ════════════════════════════════════════════════════════════

def run_generate(yaml_text: str, max_cases: Optional[int] = None,
                 seed: Optional[int] = None) -> Dict[str, Any]:
    """YAML 文本 → case 属性表（文档十六节最小字段集 + 专题 / 树路径）。"""
    try:
        models = load_models_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    # 多对象时每个对象各生成一套（case_id 的 TC-<对象代号>-… 前缀各自独立）
    result = generate_many(models, seed=seed, max_cases=max_cases)
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


def _ascii_key(text: str) -> str:
    """一段文本 → ASCII 标识符片段。

    **故意与 `uvm_tools` 里的同名逻辑各写一份**：本仓库的规矩是工具之间不互相
    import（见 readme 的分层约定）。两边的约定靠**各自的测试**钉住
    （都断言输出全 ASCII、且同一维度给出同一个键），不靠共享代码 ——
    共享代码就等于互相依赖。
    """
    import re as _re
    return _re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").lower() or "attr"


def _int_value_of(token: str, index: int) -> int:
    """取值的整型投影：本身是数字就用它，否则用它在字段里的下标。

    数字优先是有意的 —— 反压比例 `50` 的机器通道该是 50 而不是「第 3 个取值」，
    消费方（sequence）拿到 50 才谈得上「按比例压」。
    """
    try:
        return int(str(token).strip())
    except (TypeError, ValueError):
        return index


def run_uvm_tests(yaml_text: str, *, dimensions: Optional[List[str]] = None,
                  max_tests: Optional[int] = None) -> Dict[str, Any]:
    """YAML 文本 → `tool_uvm` 的 `environment.tests` 片段。

    **一条 = 一个 UVM_TEST = 一个属性取值**：把模型里每个维度字段的取值点摊平成
    一份列表。产物是**文本**（一段 YAML），不是运行时调用 —— `uvm_tools` 不 import
    本工具，本工具也不 import 它；把这段贴进 env 清单的 `environment:` 下即可。

    `dimensions` 按维度 id / 名称 / key 过滤（不给就是全部维度）。
    `max_tests` 截断时**不静默**：`truncated` / `dropped` / `notes` 都记账，
    且**优先保留边界取值** —— 但边界是**跨维度按声明顺序**挑的，不是集中在某一个
    维度上。所以 `--max-tests 4` 拿到的是「前几个维度各自的边界值」，想只要反压
    比例的四个边界要同时给 `--dimensions D_ratio`。
    """
    try:
        models = load_models_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    # `tests:` 列了多个对象时，**维度空间是共享的** —— 属性取值空间只有一个，
    # 所以这个列表与对象数无关，取第一个模型（= 共享空间）即可。
    model = models[0]
    wanted = set(dimensions or ())
    picked: List[Dict[str, Any]] = []
    for dim in model.dimensions:
        if wanted and not (wanted & {dim.id, dim.name, dim.key}):
            continue
        key = _ascii_key(dim.id or dim.name)
        for fld in dim.fields:
            for index, point in enumerate(fld.value_points()):
                picked.append({
                    "dimension": dim.id or dim.name,
                    "value": point.token,
                    "key": key,
                    "int_value": _int_value_of(point.token, index),
                    # 只用于排序，不进 YAML —— schema 是 additionalProperties: false
                    "_boundary": bool(point.boundary),
                })

    total = len(picked)
    truncated = max_tests is not None and 0 <= max_tests < total
    notes: List[str] = []
    if truncated:
        # 边界优先 + 稳定的声明顺序（同 CaseBuilder 的纪律：截断要记账、
        # 结果要能 diff）
        order = sorted(range(total), key=lambda i: (not picked[i]["_boundary"], i))
        keep = sorted(order[:max_tests])
        picked = [picked[i] for i in keep]
        notes.append(
            f"tests 截断到 {max_tests} 条，丢弃 {total - len(picked)} 条"
            f"（优先保留边界取值）；用 --max-tests 调整")

    tests = [{k: v for k, v in entry.items() if not k.startswith("_")}
             for entry in picked]
    return {
        "count": len(tests),
        "total_before_cap": total,
        "truncated": truncated,
        "dropped": total - len(tests),
        "notes": notes,
        "dimensions_used": sorted({t["dimension"] for t in tests}),
        "tests": tests,
        "tests_yaml": yaml.safe_dump({"tests": tests}, allow_unicode=True,
                                     sort_keys=False),
    }


#: 工具名 → 实现，供适配器一次性遍历。
#: 与 `TOOL_NAMES` **必须一致**（有测试钉住）：适配器拿它建三面的工具表，
#: 多一个名字就会在 `classes[name]` 上 KeyError。
RUNNERS = {
    TOOL_VALIDATE: run_validate,
    TOOL_GAPS: run_gaps,
    TOOL_GENERATE: run_generate,
}
