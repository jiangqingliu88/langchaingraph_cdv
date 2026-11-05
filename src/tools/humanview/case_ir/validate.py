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

from typing import Any, Dict, List

from .ir_core import CaseDoc


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
            "bound_tests": sum(1 for c in doc.cases if c.tests),
            "bound_cells": sum(1 for c in doc.cases if c.cells),
        },
    }


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
        for cid in case.categories:
            if cid not in known_cats:
                errors.append({"rule": "unknown_category", "target": case.id,
                               "message": f"用例 {case.id} 指向不存在的分类：{cid}"})
        if not case.tests and not case.dimensions:
            errors.append({"rule": "case_without_binding", "target": case.id,
                           "message": f"用例 {case.id} 既没有 tests 也没有 dimensions —— "
                                      f"它落不到任何可执行实例"})
        if not case.cells:
            warnings.append({"rule": "case_without_cells", "target": case.id,
                             "message": f"用例 {case.id} 没有 cells 声明（CELL 仍会由 "
                                        f"cell_matrix 派生）"})

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


__all__ = ["validate_case_doc"]
