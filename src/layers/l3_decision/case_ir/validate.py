"""Case IR 的结构校验 —— 只回答“这份用例身份立不立得住”。

与 `case_model.schema.json` 的分工：schema 管字段类型，这里管**引用与唯一性**
（JSON Schema 看不见“CASE 指向的分类不存在”这类语义问题）。

规则（error 会挡住写盘 / 阻断门禁）：
  · `id` 全局唯一（分类与用例各自唯一，且不互相撞）
  · 分类的 `parent` 必须存在（根除外）
  · CASE 的 `category` 必须存在
  · CASE 至少有一个 `tests` 或 `dimensions`（否则它落不到任何可执行实例）
warning：
  · 空文档（没有 CASE）
  · 分类叶子下没有 CASE
  · CASE 没有 `cells` 声明（CELL 由 cell_matrix 派生，声明只是意图）
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from .ir_core import CaseDoc

#: 一条豁免必须带齐的字段 —— 少一个就不是"被批准的不适用"。
_WAIVER_FIELDS = ("id", "owner", "approver", "reason", "expires")


def _result(errors: List[Dict[str, str]], warnings: List[Dict[str, str]],
            doc: CaseDoc) -> Dict[str, Any]:
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "categories": len(doc.categories),
            "cases": len(doc.cases),
            "declared": sum(1 for c in doc.cases if c.source == "declared"),
            "synthesized": sum(1 for c in doc.cases if c.source == "synthesized"),
            "xlsx": sum(1 for c in doc.cases if c.source == "xlsx"),
            "bound_tests": sum(1 for c in doc.cases if c.tests),
            "bound_cells": sum(1 for c in doc.cases if c.cells),
        },
    }


def _waiver_issues(case, errors: List[Dict[str, str]],
                   warnings: List[Dict[str, str]]) -> None:
    """豁免必须**完整且未过期**；没有审批人的"不适用"不算豁免。"""
    for item in getattr(case, "waivers", None) or []:
        missing = [k for k in _WAIVER_FIELDS
                   if not str((item or {}).get(k) or "").strip()]
        if missing:
            errors.append({"rule": "waiver_incomplete", "target": case.id,
                           "message": f"豁免 {item.get('id') or '?'} 缺少字段：{missing}"})
        expires = str((item or {}).get("expires") or "")
        if not expires:
            continue
        try:
            if date.fromisoformat(expires) < date.today():
                warnings.append({"rule": "waiver_expired", "target": case.id,
                                 "message": f"豁免 {item.get('id')} 已于 {expires} 过期"})
        except ValueError:
            errors.append({"rule": "waiver_invalid_date", "target": case.id,
                           "message": f"豁免 {item.get('id')} 的 expires 不是 ISO 日期：{expires}"})


def _case_issues(case, known_cats, errors: List[Dict[str, str]],
                 warnings: List[Dict[str, str]]) -> None:
    for cid in case.categories:
        if cid not in known_cats:
            errors.append({"rule": "unknown_category", "target": case.id,
                           "message": f"用例 {case.id} 指向不存在的分类：{cid}"})
    _waiver_issues(case, errors, warnings)
    if not case.tests and not case.dimensions:
        errors.append({"rule": "case_without_binding", "target": case.id,
                       "message": f"用例 {case.id} 既没有 tests 也没有 dimensions —— "
                                  f"它落不到任何可执行实例"})
    elif case.source == "xlsx" and not case.dimensions:
        warnings.append({"rule": "xlsx_case_without_dimensions", "target": case.id,
                         "message": f"业务用例 {case.id} 没有 dimensions 绑定 —— "
                                    f"只能按测试名落到执行实例，CELL/覆盖仓接不上"})
    if not case.cells:
        warnings.append({"rule": "case_without_cells", "target": case.id,
                         "message": f"用例 {case.id} 没有 cells 声明（CELL 仍会由 "
                                    f"cell_matrix 派生）"})


def validate_case_doc(doc: CaseDoc) -> Dict[str, Any]:
    """CaseDoc → `{ok, errors[], warnings[], metrics{}}`。"""
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    cat_ids = [c.id for c in doc.categories]
    seen: Dict[str, str] = {}
    for cid in cat_ids:
        if cid in seen:
            errors.append({"rule": "duplicate_id", "target": cid,
                           "message": f"分类 ID 重复：{cid}"})
        seen[cid] = "category"
    for case in doc.cases:
        if case.id in seen:
            errors.append({"rule": "duplicate_id", "target": case.id,
                           "message": f"用例 ID 重复或与分类撞车：{case.id}"})
        seen[case.id] = "case"

    known_cats = set(cat_ids)
    for cat in doc.categories:
        if cat.parent and cat.parent not in known_cats:
            errors.append({"rule": "unknown_parent", "target": cat.id,
                           "message": f"分类 {cat.id} 的 parent 不存在：{cat.parent}"})

    for case in doc.cases:
        _case_issues(case, known_cats, errors, warnings)

    if not doc.cases:
        warnings.append({"rule": "no_cases", "target": doc.module or "<model>",
                         "message": "Case IR 里没有任何用例"})
    else:
        with_case = {cid for c in doc.cases for cid in c.categories}
        for cat in doc.categories:
            is_leaf = not any(c.parent == cat.id for c in doc.categories)
            if is_leaf and cat.id not in with_case:
                warnings.append({"rule": "empty_category_leaf", "target": cat.id,
                                 "message": f"分类叶子 {cat.id} 下没有用例"})

    return _result(errors, warnings, doc)


def validate_case_closure(doc: CaseDoc, *,
                          known_dimensions: Optional[List[str]] = None,
                          known_tests: Optional[List[str]] = None) -> Dict[str, Any]:
    """**引用闭合**：CASE 指向的维度/测试/checker 必须真的落得下去。

    与 `validate_case_doc` 的分工：那个查"身份自身是否合法"，这里查
    "身份与模型/执行层的引用是否闭合"。`known_*` 为空表示该侧不校验
    （例如投影阶段还没有模型），不冒充通过。
    """
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    dims = {str(d) for d in (known_dimensions or []) if str(d)}
    tests = {str(t) for t in (known_tests or []) if str(t)}

    for case in doc.cases:
        for dim in case.dimensions:
            if dims and dim not in dims:
                errors.append({
                    "rule": "unknown_dimension", "target": case.id,
                    "message": f"用例 {case.id} 绑定的维度 {dim} 不在 casemodel 的 "
                               f"dimensions 里"})
        if tests:
            for test in case.tests:
                if test not in tests:
                    warnings.append({
                        "rule": "unknown_test", "target": case.id,
                        "message": f"用例 {case.id} 的测试类 {test} 不在生成清单里"})
        for key in ("sva", "scb"):
            for item in getattr(case, key, None) or []:
                if not (item.get("tp_ids") or []):
                    errors.append({
                        "rule": "checker_without_tp", "target": case.id,
                        "message": f"用例 {case.id} 的 {key} {item.get('id') or '?'} "
                                   f"没有绑定任何 TP"})
    return {
        "schema": "case_closure_v1",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {"cases": len(doc.cases), "dimensions": len(dims),
                    "tests": len(tests)},
    }


__all__ = ["validate_case_closure", "validate_case_doc"]
