"""AIVM 只读视图 API —— 给工作台/CLI 用，不写盘、不起 EDA。

`summarize_xlsx(path)`：加载测试点表 → 校验统计 → M1 计划摘要 + 每 TP 一行。
这是 Workbench「测试点表（xlsx）」页的绑定目标（`humanview.aivm_plan`）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def _tp_row(tp: Any) -> Dict[str, Any]:
    from .ir_core import RawColumn

    # **源表原文**：GUI 的「测试点表（xlsx）」按 xlsx 的表头逐列显示，
    # 所以这里把锚点行的原始单元格原样带出去（不切词、不复算）。
    # 多行 TP 的 C/D/E 后续行不并进来 —— 表格是"一 TP 一行"的清单，
    # 原表的逐行结构在别处（`raw_rows` / 覆盖格）已有完整记录。
    raw = tp.raw_rows[0] if tp.raw_rows else {}

    def _raw(key: Any, fallback: Any = "") -> Any:
        value = raw.get(key.value, "")
        return value if value not in (None, "") else fallback

    return {
        "tp_id": tp.tp_id,
        "orig_id": tp.orig_id or tp.tp_id,
        "category": tp.category.value,
        "mode": tp.execution_mode.value,
        "name": (tp.feature_text or "")[:80],
        "cover_bins": len(tp.cover_bin_cells()),
        "config_enums": len(tp.config_enum_cells()),
        "directed_cases": len(tp.directed_case_cells()),
        # ── xlsx 原文列（表头见 `xlsx_loader.RawColumn` / 示例表）──
        "seq": tp.orig_id or tp.tp_id,
        "feature": _raw(RawColumn.FEATURE, tp.feature_text),
        "sub_feature": _raw(RawColumn.SUB_FEATURE),
        "sub_sub_feature": _raw(RawColumn.SUB_SUB_FEATURE),
        "sub_sub_sub_feature": _raw(RawColumn.SUB_SUB_SUB_FEATURE),
        "test_name": _raw(RawColumn.TEST_NAME, tp.test_name or ""),
        "test_num": _raw(RawColumn.TEST_NUM,
                         "" if tp.test_num is None else tp.test_num),
        "doc_section": _raw(RawColumn.DOC_SECTION, tp.provenance.doc_section),
        "chapter": _raw(RawColumn.CHAPTER, tp.provenance.chapter),
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
    # **表头按源表发现**（不是 GUI 写死一份）：`discover_column_headers`
    # 读第 2/3 行，与 loader 的列映射同源；界面照它出列。
    columns: List[Dict[str, Any]] = []
    try:
        from openpyxl import load_workbook
        from .xlsx_loader import discover_column_headers

        wb = load_workbook(target, data_only=True)
        try:
            columns = discover_column_headers(wb.worksheets[0])
        finally:
            wb.close()
    except Exception:                              # noqa: BLE001 只读视图不抛
        columns = []
    return {
        "available": True,
        "path": str(target),
        "columns": columns,
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
