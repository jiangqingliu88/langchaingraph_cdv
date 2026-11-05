"""SVA IR 校验 + 完整性度量（契约覆盖 / 格子绑定 / 非 vacuous / 七类 / 重复）。

**vacuous 是错误，不是警告**：antecedent 从未触发的 SVA 永远 pass，等于没验证。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..ir_common import duplicates, metric, result
from .ir_core import SVA_CLASSES, SVADoc


def _norm_expr(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _semantic_key(sva) -> str:
    if sva.property:
        return _norm_expr(sva.property)
    return f"{_norm_expr(sva.antecedent)}|->{_norm_expr(sva.consequent)}"


def sva_status(sva) -> str:
    """单条 SVA 的展示态：green / yellow / red / na。"""
    if sva.fail_count > 0:
        return "red"
    if sva.hit_count <= 0:
        return "red"                     # vacuous
    return "green"


def build_matrix(doc: SVADoc) -> Dict[str, Any]:
    cells = list(doc.cells)
    for sva in doc.svas:
        for cell in sva.bound_cells:
            if cell not in cells:
                cells.append(cell)
    rows = [{"sva": s.id, "contract": s.contract,
             "class": s.klass, "status": sva_status(s),
             "cells": {cell: ("green" if cell in s.bound_cells else "na")
                       for cell in cells}}
            for s in doc.svas]
    return {"cells": cells, "rows": rows}


def _validate_one(sva, doc: SVADoc, errors: List[str],
                  warnings: List[str]) -> None:
    missing = []
    if not sva.contract:
        missing.append("contract")
    if not sva.klass:
        missing.append("class")
    if not sva.antecedent:
        missing.append("antecedent")
    if not sva.consequent:
        missing.append("consequent")
    if not sva.cover_property:
        missing.append("cover_property")
    if not sva.bound_cells:
        missing.append("bound_cells")
    if missing:
        errors.append(f"{sva.id}: 缺必填项 {'、'.join(missing)}")
    if sva.klass and sva.contract and doc.contracts and sva.contract not in doc.contracts:
        warnings.append(f"{sva.id}: contract {sva.contract} 不在 contracts 清单里")
    if not sva.property:
        warnings.append(f"{sva.id}: 没有 property（只有 antecedent/consequent）")
    if sva.hit_count <= 0:
        errors.append(f"{sva.id}: antecedent 从未触发（vacuous pass，等于没验证）")
    if sva.fail_count > 0:
        errors.append(f"{sva.id}: 已触发失败 {sva.fail_count} 次")
    if sva.bound_cells and doc.cells:
        unknown = [c for c in sva.bound_cells if c not in doc.cells]
        if unknown:
            warnings.append(f"{sva.id}: 绑定了不在 cells 清单里的格子 "
                            f"{'、'.join(unknown)}")


def _metrics(doc: SVADoc, contracts: List[str], cells: List[str],
             dup_count: int) -> list:
    by_class: Dict[str, int] = {}
    for sva in doc.svas:
        by_class[sva.klass or "?"] = by_class.get(sva.klass or "?", 0) + 1
    with_sva_contracts = {s.contract for s in doc.svas if s.contract}
    with_sva_cells = {c for s in doc.svas for c in s.bound_cells}
    non_vacuous = sum(1 for s in doc.svas if s.hit_count > 0)
    return [
        metric("契约覆盖", len(with_sva_contracts & set(contracts)), len(contracts)),
        metric("格子绑定", len(with_sva_cells & set(cells)), len(cells)),
        metric("非 vacuous", non_vacuous, len(doc.svas)),
        metric("七类覆盖", len([c for c in SVA_CLASSES if by_class.get(c)]),
               len(SVA_CLASSES)),
        metric("非重复", max(0, len(doc.svas) - dup_count), len(doc.svas)),
    ]


def validate_sva(doc: SVADoc) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    contracts = list(doc.contracts) or sorted({s.contract for s in doc.svas if s.contract})
    cells = list(doc.cells) or sorted({c for s in doc.svas for c in s.bound_cells})
    for sva in doc.svas:
        _validate_one(sva, doc, errors, warnings)

    dup = duplicates(doc.svas, _semantic_key)
    for key, rows in dup.items():
        errors.append("语义重复的 SVA（property 相同）："
                      + "、".join(s.id for s in rows))
    dup_count = sum(len(v) - 1 for v in dup.values())
    by_class: Dict[str, int] = {}
    for sva in doc.svas:
        by_class[sva.klass or "?"] = by_class.get(sva.klass or "?", 0) + 1
    return result(errors, warnings, _metrics(doc, contracts, cells, dup_count), {
        "by_class": by_class,
        "by_status": {s: sum(1 for x in doc.svas if sva_status(x) == s)
                      for s in ("green", "yellow", "red", "na")},
        "matrix": build_matrix(doc),
        "duplicates": {k: [s.id for s in v] for k, v in dup.items()},
    })
