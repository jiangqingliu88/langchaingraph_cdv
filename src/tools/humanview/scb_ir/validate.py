"""SCB IR 校验 + 完整性度量（契约/格子/执行率/五类/重复/账本平衡）。

**执行率为 0 是错误**：写了但从未执行的检查项等于没写。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..ir_common import duplicates, metric, result
from .ir_core import SCB_CLASSES, SCBDoc

_DUT_WORDS = ("dut", "reg", "寄存器回读", "读回 dut")


def scb_status(scb) -> str:
    if scb.fail_count > 0 or scb.outstanding > 0 or scb.residual > 0:
        return "red"
    if scb.execute_count <= 0:
        return "red"                    # 未执行
    return "green"


def _norm_source(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _duplicate_key(scb) -> str:
    return "|".join(_norm_source(x) for x in
                    (scb.check_object, scb.expected_source, scb.method))


def build_matrix(doc: SCBDoc) -> Dict[str, Any]:
    cells = list(doc.cells)
    for scb in doc.checks:
        for cell in scb.bound_cells:
            if cell not in cells:
                cells.append(cell)
    rows = [{"scb": s.id, "contract": s.contract, "class": s.klass,
             "status": scb_status(s),
             "cells": {cell: ("green" if cell in s.bound_cells else "na")
                       for cell in cells}}
            for s in doc.checks]
    return {"cells": cells, "rows": rows}


def _required_errors(scb, errors: List[str]) -> None:
    missing = [name for name, value in (
        ("contract", scb.contract), ("class", scb.klass), ("model", scb.model),
        ("expected_source", scb.expected_source),
        ("bound_cells", scb.bound_cells)) if not value]
    if missing:
        errors.append(f"{scb.id}: 缺必填项 {'、'.join(missing)}")


def _count_errors(scb, errors: List[str], warnings: List[str]) -> None:
    if scb.execute_count <= 0:
        errors.append(f"{scb.id}: execute_count=0（从未执行，等于没写）")
    elif scb.pass_count + scb.fail_count != scb.execute_count:
        warnings.append(f"{scb.id}: pass+fail != execute_count "
                        f"（{scb.pass_count}+{scb.fail_count} != {scb.execute_count}）")
    if scb.fail_count > 0:
        errors.append(f"{scb.id}: 比对失败 {scb.fail_count} 次")
    if scb.outstanding > 0:
        errors.append(f"{scb.id}: 账本未平（outstanding={scb.outstanding}）")
    if scb.residual > 0:
        errors.append(f"{scb.id}: 结束残留 {scb.residual}")


def _source_warnings(scb, warnings: List[str]) -> None:
    if scb.expected_source and scb.actual_source:
        exp, act = _norm_source(scb.expected_source), _norm_source(scb.actual_source)
        if exp == act or any(w in exp for w in _DUT_WORDS):
            warnings.append(f"{scb.id}: 期望来源可能依赖 DUT 自身（"
                            f"{scb.expected_source} / {scb.actual_source}）"
                            f"—— 不是独立比对")
    if not scb.check_object:
        warnings.append(f"{scb.id}: 没有 check_object（比什么不清楚）")
    if not scb.timing:
        warnings.append(f"{scb.id}: 没有 timing（什么时候比不清楚）")


def _binding_warnings(scb, doc: SCBDoc, warnings: List[str]) -> None:
    if scb.contract and doc.contracts and scb.contract not in doc.contracts:
        warnings.append(f"{scb.id}: contract {scb.contract} 不在 contracts 清单里")
    if scb.bound_cells and doc.cells:
        unknown = [c for c in scb.bound_cells if c not in doc.cells]
        if unknown:
            warnings.append(f"{scb.id}: 绑定了不在 cells 清单里的格子 "
                            f"{'、'.join(unknown)}")


def _validate_one(scb, doc: SCBDoc, errors: List[str],
                  warnings: List[str]) -> None:
    _required_errors(scb, errors)
    _count_errors(scb, errors, warnings)
    _source_warnings(scb, warnings)
    _binding_warnings(scb, doc, warnings)


def _metrics(doc: SCBDoc, contracts: List[str], cells: List[str],
             dup_count: int) -> list:
    by_class: Dict[str, int] = {}
    for scb in doc.checks:
        by_class[scb.klass or "?"] = by_class.get(scb.klass or "?", 0) + 1
    with_scb_contracts = {c.contract for c in doc.checks if c.contract}
    with_scb_cells = {c for s in doc.checks for c in s.bound_cells}
    executed = sum(1 for c in doc.checks if c.execute_count > 0)
    ledgers = [c for c in doc.checks if c.klass == "SB3"]
    balanced = sum(1 for c in ledgers if c.outstanding == 0 and c.residual == 0)
    return [
        metric("契约覆盖", len(with_scb_contracts & set(contracts)), len(contracts)),
        metric("格子绑定", len(with_scb_cells & set(cells)), len(cells)),
        metric("执行率", executed, len(doc.checks)),
        metric("五类覆盖", len([c for c in SCB_CLASSES if by_class.get(c)]),
               len(SCB_CLASSES)),
        metric("非重复", max(0, len(doc.checks) - dup_count), len(doc.checks)),
        metric("账本平衡", balanced, len(ledgers)),
    ]


def validate_scb(doc: SCBDoc) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    contracts = list(doc.contracts) or sorted({c.contract for c in doc.checks if c.contract})
    cells = list(doc.cells) or sorted({c for s in doc.checks for c in s.bound_cells})
    for scb in doc.checks:
        _validate_one(scb, doc, errors, warnings)

    dup = duplicates(doc.checks, _duplicate_key)
    for key, rows in dup.items():
        warnings.append("疑似重复的 SCB：" + "、".join(c.id for c in rows))
    dup_count = sum(len(v) - 1 for v in dup.values())
    by_class: Dict[str, int] = {}
    for scb in doc.checks:
        by_class[scb.klass or "?"] = by_class.get(scb.klass or "?", 0) + 1
    return result(errors, warnings, _metrics(doc, contracts, cells, dup_count), {
        "by_class": by_class,
        "by_status": {s: sum(1 for c in doc.checks if scb_status(c) == s)
                      for s in ("green", "yellow", "red", "na")},
        "matrix": build_matrix(doc),
        "duplicates": {k: [c.id for c in v] for k, v in dup.items()},
    })
