"""把 TP IR 聚合成 **case 三集合契约**（groups / sva / scb）。

为什么从测试点反聚合、而不是让人再写一遍：

    TP 已经有 case_id、dimension、stage、checks，断言已经有 tp_bindings。
    再让人在 `cases:` 里手写一遍 groups/sva/scb，就是**两处维护**——改了一边
    另一边不会报错，只会静默漂。所以契约由 TP 反向聚合，人只维护 TP 这一层。

## 三集合的判定口径

| 集合 | 来源 | 空集合时 |
|---|---|---|
| `groups` | 该 case 的 TP 的 `dimension` × `stage` | **不允许为空**（门禁 `CASE_GROUPS_EMPTY`） |
| `sva` | 模型 `assertions[].tp_bindings` 命中该 case 的 TP | 写 `not_applicable.sva` 原因 |
| `scb` | 模型 `cases[].scb`（显式声明）或 TP 的 `checks` | 写 `not_applicable.scb` 原因 |

`scb` 默认**不合成**：本工程的 scoreboard 实体还没有接入 IR（`scb_ir` 只在
humanview 里做结构校验，没进 run）。拿 `checks` 去编一个 `SB-*` 等于把"该检查
什么"冒充成"已经检查了"——所以空着并写明原因，等 scb_ir 接入再填。

## `required_layers`

由该组下 TP 的实现类型决定：

    路径型（kind=path/sequence）   → functional + path
    行为型（kind=behavior）        → functional
    其余（属性型）                 → functional + timing + data
"""
from __future__ import annotations

from typing import Any, Dict, List

from .ir_core import CaseDoc, group_id_of, scb_id_of, sva_id_of

#: 按实现类型给该组要求的证据层。
LAYERS_ATTRIBUTE = ["functional", "timing", "data"]
LAYERS_PATH = ["functional", "path"]
LAYERS_BEHAVIOR = ["functional"]

NA_SVA = "模型未声明断言（`assertions:` 为空）或断言未绑定到本用例的测试点"
NA_SCB = "模型未声明 scoreboard 实体（`scb_ir` 尚未接入 run）；env 的 [SCB_DUT] 结果按用例记录在 case_cov.scb"


def _cell_of(tp: Dict[str, Any]) -> str:
    """`CELL-<group 短名>-<P>` —— 与 `cell_matrix.cell_id_of` 同一口径。"""
    from src.tools.checking.coverage_tools.cell_matrix import cell_id_of

    return cell_id_of(tp.get("dimension"), _stage_of(tp))


def _stage_of(tp: Dict[str, Any]) -> str:
    return str((tp.get("execution") or {}).get("stage") or tp.get("stage") or "")


def _required_layers(group: str) -> List[str]:
    """按**组**给证据层要求（组名已经表达了它是什么类型的组）。"""
    name = str(group or "").upper()
    if name.endswith("-PATH") or name.endswith("_PATH"):
        return list(LAYERS_PATH)
    if name.startswith("CG-BEH") or name.startswith("CG_BEH"):
        return list(LAYERS_BEHAVIOR)
    return list(LAYERS_ATTRIBUTE)


def _group_entries(tps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """(dimension, stage) → 一条 group 契约项。"""
    buckets: Dict[tuple, List[Dict[str, Any]]] = {}
    for tp in tps:
        key = (group_id_of(tp.get("dimension")), _stage_of(tp))
        if key[0]:
            buckets.setdefault(key, []).append(tp)
    out: List[Dict[str, Any]] = []
    for (group, stage), members in sorted(buckets.items()):
        out.append({
            "group": group,
            "cell": _cell_of(members[0]),
            "stage": stage,
            "required_layers": _required_layers(group),
            "tp_ids": [str(t.get("tp_id") or "") for t in members if t.get("tp_id")],
        })
    return out


def _sva_entries(tps: List[Dict[str, Any]],
                 assertions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """断言 → 契约项；`cell` 取它**主绑定** TP 所在格。"""
    by_id = {str(t.get("tp_id") or ""): t for t in tps}
    out: List[Dict[str, Any]] = []
    for assertion in assertions or []:
        bound = [str(tid) for tid in (assertion.get("tp_ids") or []) if tid in by_id]
        if not bound:
            continue
        roles = assertion.get("roles") or {}
        primary = next((tid for tid in bound if roles.get(tid) == "primary"), bound[0])
        out.append({
            "id": sva_id_of(assertion.get("assertion_id")),
            "name": str(assertion.get("name") or ""),
            "cell": _cell_of(by_id[primary]),
            "required": True,
            "tp_ids": bound,
        })
    return out


def _declared_scb(case: Any, by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in getattr(case, "scb", None) or []:
        if isinstance(item, str):
            item = {"id": item}
        if not isinstance(item, dict) or not item.get("id"):
            continue
        target = str(item.get("tp_id") or "")
        cell = str(item.get("cell") or "")
        if not cell and target in by_id:
            cell = _cell_of(by_id[target])
        out.append({"id": str(item["id"]), "cell": cell,
                    "required": bool(item.get("required", True)),
                    "tp_ids": [target] if target else []})
    return out


def _scoreboard_tps(sb: Dict[str, Any],
                    tps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """这条 SB 覆盖哪些 TP：显式绑定优先，其次按 `checks` 求交集。"""
    bound = {str(b.get("tp_id")) for b in (sb.get("tp_bindings") or [])
             if isinstance(b, dict) and b.get("tp_id")}
    if bound:
        return [t for t in tps if str(t.get("tp_id")) in bound]
    checks = {str(c) for c in (sb.get("checks") or []) if str(c)}
    if not checks:
        return []
    return [t for t in tps
            if checks & {str(c) for c in (t.get("checks") or [])}]


def _scb_entries(case: Any, tps: List[Dict[str, Any]],
                 scoreboards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """声明式 scb 优先；否则由模型 `scoreboards:` 聚合（按绑定/checks）。"""
    by_id = {str(t.get("tp_id") or ""): t for t in tps}
    out = _declared_scb(case, by_id)
    if out:
        return out
    for sb in scoreboards or []:
        sb_id = str(sb.get("id") or "")
        members = _scoreboard_tps(sb, tps)
        if not sb_id or not members:
            continue
        roles = {str(b.get("tp_id")): b.get("role")
                 for b in (sb.get("tp_bindings") or []) if isinstance(b, dict)}
        primary = next((t for t in members
                        if roles.get(str(t.get("tp_id"))) == "primary"),
                       members[0])
        out.append({
            "id": scb_id_of(sb_id),
            "name": str(sb.get("name") or ""),
            "cell": _cell_of(primary),
            "required": True,
            "evidence": str(sb.get("evidence") or "auto"),
            "tp_ids": [str(t.get("tp_id")) for t in members],
        })
    return out


def attach_contracts(doc: CaseDoc, tps: List[Dict[str, Any]],
                     assertions: List[Dict[str, Any]] = None,
                     scoreboards: List[Dict[str, Any]] = None) -> CaseDoc:
    """给每条 case 填三集合（原地修改并返回 doc）。"""
    if doc is None or doc.empty:
        return doc
    by_case: Dict[str, List[Dict[str, Any]]] = {}
    for tp in tps or []:
        cid = str(tp.get("case_id") or "")
        if cid:
            by_case.setdefault(cid, []).append(tp)
    for case in doc.cases:
        members = by_case.get(case.id) or []
        case.groups = _group_entries(members)
        case.sva = _sva_entries(members, assertions or [])
        case.scb = _scb_entries(case, members, scoreboards or [])
        na = dict(case.not_applicable or {})
        if not case.sva:
            na.setdefault("sva", NA_SVA)
        else:
            na.pop("sva", None)
        if not case.scb:
            na.setdefault("scb", NA_SCB)
        else:
            na.pop("scb", None)
        case.not_applicable = na
        # cells 与三集合保持一致（有人手写的 extras 不丢）
        derived = {g["cell"] for g in case.groups if g.get("cell")}
        derived |= {s["cell"] for s in case.sva if s.get("cell")}
        case.cells = sorted(set(case.cells) | derived)
    doc.reindex()
    return doc


def group_map(doc: CaseDoc) -> Dict[str, Any]:
    """`case_group_map.json` —— case ↔ group ↔ cell 的正反查。"""
    rows, index, cell_index = [], {}, {}
    for case in doc.cases:
        groups: Dict[str, Dict[str, Any]] = {}
        for item in case.groups:
            g = str(item.get("group") or "")
            if not g:
                continue
            slot = groups.setdefault(g, {"group": g, "cells": [],
                                         "required_layers": item.get("required_layers") or [],
                                         "tp_ids": []})
            if item.get("cell") and item["cell"] not in slot["cells"]:
                slot["cells"].append(item["cell"])
            slot["tp_ids"].extend(item.get("tp_ids") or [])
            if item.get("cell"):
                cell_index.setdefault(item["cell"], []).append(
                    {"case": case.id, "group": g})
        rows.append({"case_id": case.id, "groups": list(groups.values())})
        for g in groups:
            index.setdefault(g, []).append(case.id)
    return {
        "schema": "case_group_map_v1",
        "counts": {"cases": len(rows), "groups": len(index),
                   "cells": len(cell_index)},
        "cases": rows,
        "index": {g: sorted(set(v)) for g, v in sorted(index.items())},
        "cell_index": {c: v for c, v in sorted(cell_index.items())},
    }


def checker_map(doc: CaseDoc) -> Dict[str, Any]:
    """`case_checker_map.json` —— case ↔ SVA/SB ↔ cell 的正反查。"""
    rows, sva_index, scb_index = [], {}, {}
    for case in doc.cases:
        rows.append({
            "case_id": case.id,
            "sva": [dict(s) for s in case.sva],
            "scb": [dict(s) for s in case.scb],
            "not_applicable": dict(case.not_applicable or {}),
        })
        for item in case.sva:
            sva_index.setdefault(str(item.get("id") or ""), []).append(case.id)
        for item in case.scb:
            scb_index.setdefault(str(item.get("id") or ""), []).append(case.id)
    return {
        "schema": "case_checker_map_v1",
        "counts": {"cases": len(rows), "sva": len(sva_index),
                   "scb": len(scb_index)},
        "cases": rows,
        "index": {"sva": {k: sorted(set(v)) for k, v in sorted(sva_index.items())},
                  "scb": {k: sorted(set(v)) for k, v in sorted(scb_index.items())}},
    }


__all__ = [
    "LAYERS_ATTRIBUTE", "LAYERS_BEHAVIOR", "LAYERS_PATH",
    "attach_contracts", "checker_map", "group_map",
]
