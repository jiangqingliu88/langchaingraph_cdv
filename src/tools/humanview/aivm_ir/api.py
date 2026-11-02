"""AIVM 只读视图 API —— 给工作台/CLI 用，不写盘、不起 EDA。

`summarize_xlsx(path)`：加载测试点表 → 校验统计 → M1 计划摘要 + 每 TP 一行。
这是 Workbench「测试点表（xlsx）」页的绑定目标（`humanview.aivm_plan`）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def _tp_row(tp: Any) -> Dict[str, Any]:
    return {
        "tp_id": tp.tp_id,
        "orig_id": tp.orig_id or tp.tp_id,
        "category": tp.category.value,
        "mode": tp.execution_mode.value,
        "name": (tp.feature_text or "")[:80],
        "cover_bins": len(tp.cover_bin_cells()),
        "config_enums": len(tp.config_enum_cells()),
        "directed_cases": len(tp.directed_case_cells()),
    }


def _validate_counts(onto: Any) -> Dict[str, int]:
    from .validate import validate_ontology

    report = validate_ontology(onto, strict=False)
    blocking = [e for e in report.get("errors") or [] if not e.startswith("[")]
    return {"errors": len(blocking),
            "warnings": len(report.get("errors") or []) - len(blocking)}


def _plan_totals(onto: Any) -> Dict[str, Any]:
    try:
        from .plan_compiler_m1 import compile_ontology

        plan = compile_ontology(onto, validate=False)  # 视图不重复刷告警
        return {"available": True, "tp_count": plan.get("tp_count", 0),
                "totals": plan.get("totals") or {}}
    except Exception as exc:                       # noqa: BLE001 只读视图不抛
        return {"available": False, "error": str(exc)}


def summarize_xlsx(path: str) -> Dict[str, Any]:
    """xlsx → 只读摘要；文件缺失/解析失败返回 `{available: False, error}`。"""
    from .xlsx_loader import load_xlsx_to_ontology

    target = Path(path)
    if not target.is_file():
        return {"available": False, "error": f"文件不存在：{path}"}
    try:
        onto = load_xlsx_to_ontology(str(target))
    except Exception as exc:                       # noqa: BLE001
        return {"available": False, "error": f"加载失败：{exc}"}
    rows: List[Dict[str, Any]] = [_tp_row(tp) for tp in onto.testpoints]
    return {
        "available": True,
        "path": str(target),
        "tp_count": onto.tp_count(),
        "by_category": {k.value: len(v) for k, v in onto.category_groups().items()},
        "by_mode": _count(rows, "mode"),
        "cell_types": _count_rows(onto),
        "validate": _validate_counts(onto),
        "plan": _plan_totals(onto),
        "tps": rows,
    }


def _count(rows: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def _count_rows(onto: Any) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for tp in onto.testpoints:
        for kind, count in tp.cell_type_breakdown().items():
            out[kind] = out.get(kind, 0) + count
    return dict(sorted(out.items()))
