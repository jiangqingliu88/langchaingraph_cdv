"""covg_ir 的结构校验 + 纵横矩阵 + 完整性度量。

**这里判的是"声明是否自洽"**，不是"仿真打没打到"：
- 每个组有需求、覆盖点、矩阵归属、采样域；
- 每条路径有阶段、绑定 SVA / SCB / 定向序列；
- 每个跨组交叉有实现方式、验证意图、绑定 checker；
- 矩阵格子：缺 checker → red；有 checker 但未签核 → yellow；两边都签核 → green。

命中率来自 ucdb，不在这份 IR 里冒充。
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..ir_common import duplicates, metric, result
from .ir_core import CovgIR, CovergroupIR, PathIR


def _applicable(group: CovergroupIR, path: PathIR) -> bool:
    """这个组在这条路径上是否有契约关系。"""
    if group.matrix_rows:
        return path.id in group.matrix_rows
    if group.requirements and path.feats:
        return bool(set(group.requirements) & set(path.feats))
    return True


def _has_checker(group: CovergroupIR, path: PathIR) -> bool:
    return bool(group.evidence_sva and group.evidence_scb
                and path.bound_sva and path.bound_scoreboard)


def _cell_status(group: CovergroupIR, path: PathIR) -> str:
    if not _applicable(group, path):
        return "na"
    if not _has_checker(group, path):
        return "red"
    if group.status == "已签核" and path.status == "已签核":
        return "green"
    return "yellow"


def build_matrix(ir: CovgIR) -> Dict[str, Any]:
    """功能组 × 路径矩阵（结构状态；不是 ucdb 命中率）。"""
    groups = ir.group_ids()
    rows = []
    counts = {"green": 0, "yellow": 0, "red": 0, "na": 0}
    for path in ir.paths:
        cells = {}
        for group in ir.covergroups:
            status = _cell_status(group, path)
            cells[group.id] = status
            counts[status] = counts.get(status, 0) + 1
        rows.append({"path": path.id, "status": path.status, "cells": cells})
    return {"groups": groups, "rows": rows, "counts": counts,
            "applicable": counts["green"] + counts["yellow"] + counts["red"]}


def _traceability(ir: CovgIR) -> Dict[str, Any]:
    feats = set(ir.feats)
    for group in ir.covergroups:
        feats.update(group.requirements)
    for path in ir.paths:
        feats.update(path.feats)
    with_group = {f for g in ir.covergroups for f in g.requirements}
    with_path = {f for p in ir.paths for f in p.feats}
    orphan_cps = [
        f"{g.id}.{cp.id}" for g in ir.covergroups for cp in g.coverpoints
        if not cp.matrix_rows and not g.matrix_rows]
    orphans = sorted(f for f in feats if f not in with_group or f not in with_path)
    return {"feats": sorted(feats), "with_group": sorted(with_group),
            "with_path": sorted(with_path), "orphan_feats": orphans,
            "orphan_coverpoints": orphan_cps}


def _validate_group(group: CovergroupIR, errors: List[str],
                    warnings: List[str]) -> None:
    if not group.requirements:
        errors.append(f"{group.id}: 没有 requirements（需求追溯断链）")
    if not group.sampling_domain:
        warnings.append(f"{group.id}: 没有 sampling_domain（采样归属不明）")
    n_cp = len(group.coverpoints)
    if n_cp == 0:
        errors.append(f"{group.id}: 没有 coverpoint")
    elif n_cp < 2:
        warnings.append(f"{group.id}: 只有 {n_cp} 个 coverpoint，建议合并组")
    elif n_cp > 8:
        warnings.append(f"{group.id}: {n_cp} 个 coverpoint，建议拆组（4~8）")
    for cp in group.coverpoints:
        if not cp.signal:
            errors.append(f"{group.id}.{cp.id}: coverpoint 没有 signal")
        if not cp.bins and not cp.illegal_bins:
            errors.append(f"{group.id}.{cp.id}: 没有任何 bins（空 coverpoint）")
    known = {c.id for c in group.coverpoints} | {c.name for c in group.coverpoints}
    for cross in group.intra_cross:
        missing = [o for o in cross.objects if o not in known]
        if missing:
            errors.append(f"{group.id}.{cross.id}: 引用了解析不到的 coverpoint "
                          f"{'、'.join(missing)}")
        if len(cross.bins) > 20:
            warnings.append(f"{group.id}.{cross.id}: {len(cross.bins)} 个交叉仓，"
                            f"超过 20 建议拆分")
        for b in cross.ignore_bins:
            if not b.ignore_reason:
                warnings.append(f"{group.id}.{cross.id}: ignore_bin {b.name} "
                                f"没有理由（不可审计）")


def _validate_path(path: PathIR, errors: List[str],
                   warnings: List[str]) -> None:
    if len(path.stages) < 2:
        warnings.append(f"{path.id}: 阶段序列少于 2（无法表达生命周期）")
    if not path.coverpoint:
        errors.append(f"{path.id}: 没有序列 coverpoint")
    if not path.bound_sva:
        errors.append(f"{path.id}: 没有绑定 SVA —— 路径只构造不检查")
    if not path.bound_scoreboard:
        errors.append(f"{path.id}: 没有绑定 scoreboard —— 路径只构造不比对")
    if not path.directed_seq:
        warnings.append(f"{path.id}: 没有定向序列（路径靠随机很难稳定命中）")
    if not path.feats:
        warnings.append(f"{path.id}: 没有 feats（需求追溯断链）")


def _validate_cross(cross, cp_index: Dict[str, tuple], errors: List[str],
                    warnings: List[str]) -> None:
    missing = [o for o in cross.objects if o not in cp_index]
    if len(cross.objects) < 2 or missing:
        errors.append(f"{cross.id}: 跨组交叉对象解析不到"
                      f"（{'、'.join(missing) or '少于 2 个'}）")
    if cross.implementation not in ("cross_cg", "copied_coverpoint"):
        errors.append(f"{cross.id}: implementation 必须是 cross_cg / copied_coverpoint")
    if not cross.intent:
        warnings.append(f"{cross.id}: 没有验证意图（为了交叉而交叉）")
    if not cross.bound_sva and not cross.bound_scoreboard:
        errors.append(f"{cross.id}: 没有绑定 SVA/SCB —— 交叉不能单独签核")
    if len(cross.bins) > 20:
        warnings.append(f"{cross.id}: {len(cross.bins)} 个交叉仓，超过 20 建议拆分")


def _duplicate_errors(ir: CovgIR, errors: List[str]) -> None:
    for label, dup in (("covergroup", duplicates(ir.covergroups, lambda g: g.id)),
                       ("path", duplicates(ir.paths, lambda p: p.id)),
                       ("cross", duplicates(ir.crosses, lambda c: c.id))):
        for key in dup:
            errors.append(f"{label} ID 重复：{key}")


def _metrics(ir: CovgIR, matrix: Dict[str, Any], trace: Dict[str, Any]) -> list:
    groups_with_evidence = sum(1 for g in ir.covergroups
                               if g.evidence_sva and g.evidence_scb)
    paths_with_checker = sum(1 for p in ir.paths
                             if p.bound_sva and p.bound_scoreboard)
    feat_both = [f for f in trace["feats"]
                 if f in trace["with_group"] and f in trace["with_path"]]
    return [
        metric("纵向组有 checker", groups_with_evidence, len(ir.covergroups)),
        metric("横向路径有 checker", paths_with_checker, len(ir.paths)),
        metric("矩阵格子 green/适用", matrix["counts"]["green"],
               matrix["applicable"]),
        metric("需求双挂（组+路径）", len(feat_both), len(trace["feats"])),
    ]


def validate_covg(ir: CovgIR) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    if not ir.module:
        errors.append("缺少 module")
    if not ir.covergroups:
        errors.append("没有任何 covergroup（纵向维度为空）")
    if not ir.paths:
        warnings.append("没有任何 path（横向维度为空）—— 不能证明路径覆盖")

    for group in ir.covergroups:
        _validate_group(group, errors, warnings)
    for path in ir.paths:
        _validate_path(path, errors, warnings)
    cp_index = ir.coverpoints()
    for cross in ir.crosses:
        _validate_cross(cross, cp_index, errors, warnings)
    _duplicate_errors(ir, errors)

    matrix = build_matrix(ir)
    trace = _traceability(ir)
    for feat in trace["orphan_feats"]:
        warnings.append(f"需求 {feat} 没有同时挂到功能组和路径（孤立需求）")
    for cp in trace["orphan_coverpoints"][:20]:
        warnings.append(f"覆盖点 {cp} 没有矩阵归属（孤立覆盖点）")
    return result(errors, warnings, _metrics(ir, matrix, trace),
                  {"matrix": matrix, "traceability": trace})
