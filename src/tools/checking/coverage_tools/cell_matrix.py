"""CELL —— **CG × P 的派生签核视图**（不是实体，不许手写）。

    CG    := 测试点所属的**功能组**（TP IR 的 `dimension`）
    P     := 生命周期阶段（`execution.stage`；行为型 TP 为 `behavior`）
    CELL  := f"CELL-{CG}-{P}"

为什么 CG 取 `dimension` 而不是 covergroup 名：本工程的覆盖组是**采样域**
（`cg_<agent>_in/out`、`cg_dut`），一个采样域横跨多个功能组；而签核要问的是
“**队列管理**这条功能在 P1 上证明了没有”。`dimension` 是模型里唯一稳定的
功能分组，且从 TP IR 一路带过来，不需要再解析一遍覆盖模型。

## 状态机（缺证据不下绿）

    green  = 该 CELL 下**每条** TP 的四层证据都到 VERIFIED
    yellow = 有 TP 只到 PARTIAL / PENDING_BACKEND（覆盖不足、checker 未声明）
    red    = 有 TP NOT_VERIFIED / UNMAPPED（该证明的没证明）
    na     = 该 CELL 下一条 TP 都没有（必须写理由）

`green` 的判据**直接取** `tp_cov_evidence` 的 `contract_status`：
那是“四层证据齐了才 VERIFIED”的同一份结论，这里不重算第二遍。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.tools.humanview.case_ir import slug

SCHEMA = "cell_matrix_v1"

COLOR_GREEN = "green"
COLOR_YELLOW = "yellow"
COLOR_RED = "red"
COLOR_NA = "na"

RANK = {COLOR_NA: 0, COLOR_YELLOW: 1, COLOR_RED: 2, COLOR_GREEN: 3}


def cell_id_of(dimension: Any, stage: Any) -> str:
    """`CELL-<CG>-<P>` —— **唯一实现点**，别在别处拼。"""
    cg = slug(dimension) or "UNGROUPED"
    p = slug(stage) or "UNSTAGED"
    return f"CELL-{cg}-{p}"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _tp_stage(tp: Dict[str, Any]) -> str:
    return str(tp.get("stage")
               or (tp.get("execution") or {}).get("stage") or "")


def _tp_dimension(tp: Dict[str, Any]) -> str:
    return str(tp.get("dimension") or "")


def _contract_status(tp: Dict[str, Any], row: Dict[str, Any]) -> str:
    """证据里没给 `contract_status` 时，按行状态兜底（旧 run 兼容）。"""
    status = str(tp.get("contract_status") or "").strip()
    if status:
        return status
    row_status = str(row.get("status") or "").strip()
    if row_status in ("HIT", "BACKDOOR_HIT", "SIGNED_OFF"):
        return "PARTIAL"
    if row_status in ("PENDING_BACKEND",):
        return "PENDING_BACKEND"
    return "NOT_VERIFIED"


def cell_color(statuses: List[str]) -> str:
    """一组契约状态 → CELL 颜色。**映射在 `status_vocab`（唯一实现）**。"""
    from src.tools.checking.coverage_tools.status_vocab import cell_color as _impl

    return _impl(statuses)


def _layer_summary(layers: Dict[str, Any]) -> Dict[str, str]:
    return {k: str((v or {}).get("status") or "") for k, v in (layers or {}).items()}


def _cell_of_tp(tp: Dict[str, Any], row: Dict[str, Any],
                owner: Dict[str, Any]) -> Dict[str, Any]:
    """一条 TP → 它落在 CELL 里的那一行证据。"""
    return {
        "tp_id": str(tp.get("tp_id") or ""),
        "status": _contract_status(tp, row),
        "signed_off": bool(row.get("signed_off", tp.get("signed_off"))),
        "signed_off_by": str(row.get("signed_off_by")
                             or owner.get("signed_off_by") or ""),
        "layers": _layer_summary(tp.get("evidence_layers") or {}),
        "kind": str(row.get("kind") or ""),
    }


def _case_records(od: Path) -> List[Dict[str, Any]]:
    """`coverage/case_cov/**/*.json` —— 三集合证据的原始来源。"""
    out: List[Dict[str, Any]] = []
    for path in sorted((od / "coverage" / "case_cov").rglob("*.json")):
        if path.name.endswith(".cache"):
            continue
        rec = _read_json(path)
        if rec.get("case_id") or rec.get("groups"):
            out.append(rec)
    return out


def _slot(out: Dict[str, Dict[str, List[Dict[str, Any]]]],
          cell_id: str) -> Dict[str, List[Dict[str, Any]]]:
    return out.setdefault(cell_id, {"groups": [], "sva": [], "scb": []})


def _add_group_evidence(out, rec: Dict[str, Any], case: str) -> None:
    for item in rec.get("groups") or []:
        cell = str((item or {}).get("cell") or "")
        if not cell:
            continue
        _slot(out, cell)["groups"].append({
            "case": case, "group": item.get("group", ""),
            "functional": (item.get("functional") or {}).get("status", ""),
            "timing": (item.get("timing") or {}).get("status", ""),
            "data": (item.get("data") or {}).get("status", ""),
            "path": (item.get("path") or {}).get("status", ""),
            "result": item.get("result", ""),
        })


def _add_checker_evidence(out, rec: Dict[str, Any], case: str) -> None:
    for key in ("sva", "scb"):
        for item in rec.get(key) or []:
            cell = str((item or {}).get("cell") or "")
            if not cell:
                continue
            entry = {"case": case, "id": item.get("id", ""),
                     "status": item.get("status", "")}
            if key == "sva":
                entry["fail"] = item.get("fail", 0)
            _slot(out, cell)[key].append(entry)


def _evidence_by_cell(od: Path) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """`cell → {groups[], sva[], scb[]}`（每项带 case，供签核索引反查）。"""
    out: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for rec in _case_records(od):
        case = str(rec.get("case_id") or rec.get("task") or "")
        _add_group_evidence(out, rec, case)
        _add_checker_evidence(out, rec, case)
    return out


def _evidence_status(ev: Dict[str, List[Dict[str, Any]]]) -> str:
    """集合证据 → 色。**映射在 `status_vocab.evidence_color`（唯一实现）**。"""
    from src.tools.checking.coverage_tools.status_vocab import (
        evidence_color as _impl,
    )

    statuses = ([g.get("result") for g in ev.get("groups") or []]
                + [s.get("status") for s in ev.get("sva") or []]
                + [s.get("status") for s in ev.get("scb") or []])
    return _impl(statuses)


def _accumulate(evidence: Dict[str, Any], rows: Dict[str, Dict[str, Any]],
                by_tp: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    cells: Dict[str, Dict[str, Any]] = {}
    for tp in evidence.get("tps") or []:
        if not isinstance(tp, dict):
            continue
        tp_id = str(tp.get("tp_id") or "")
        cid = cell_id_of(_tp_dimension(tp), _tp_stage(tp))
        cell = cells.setdefault(cid, {"cell_id": cid, "cg": _tp_dimension(tp),
                                      "p": _tp_stage(tp), "tps": []})
        cell["tps"].append(_cell_of_tp(tp, rows.get(tp_id) or {},
                                       by_tp.get(tp_id) or {}))
    return cells


def _cell_reasons(color: str, tps: List[Dict[str, Any]]) -> List[str]:
    if color == COLOR_RED:
        return [f"{t['tp_id']}: {t['status']}" for t in tps
                if t["status"] in ("NOT_VERIFIED", "UNMAPPED", "MISSING")]
    if color == COLOR_YELLOW:
        return [f"{t['tp_id']}: {t['status']}" for t in tps
                if t["status"] != "VERIFIED"]
    return []


def _merge_evidence(cells: Dict[str, Dict[str, Any]],
                    evidence: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> None:
    """把 case 三集合证据挂到对应 Cell 上（没有 TP 的 Cell 也建出来）。"""
    for cell_id, ev in evidence.items():
        cell = cells.setdefault(cell_id, {
            "cell_id": cell_id, "cg": "", "p": "", "tps": []})
        if not cell.get("cg") and ev.get("groups"):
            cell["cg"] = str(ev["groups"][0].get("group") or "")
        cell["evidence"] = ev
        cell["evidence_color"] = _evidence_status(ev)


def _finalize(cells: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for _cid, cell in sorted(cells.items()):
        tps = cell["tps"]
        # 有 TP 时看 TP 的四层契约状态；没有 TP 时按 case 三集合证据判色
        color = (cell_color([t["status"] for t in tps]) if tps
                 else cell.get("evidence_color") or COLOR_NA)
        signed = sum(1 for t in tps if t["signed_off"])
        cell.update({
            "color": color,
            "tp_count": len(tps),
            "signed_off": signed,
            "signed_off_pct": round(100.0 * signed / len(tps), 1) if tps else 0.0,
            "reasons": _cell_reasons(color, tps)[:12],
            "evidence": cell.get("evidence") or {"groups": [], "sva": [], "scb": []},
            "evidence_color": cell.get("evidence_color") or COLOR_NA,
        })
        out.append(cell)
    return out


def build_cell_matrix(od: str | Path) -> Dict[str, Any]:
    """读 run 的派生物 → `cell_matrix_v1`。"""
    root = Path(od)
    cov = root / "coverage"
    evidence = _read_json(cov / "tp_cov_evidence.json")
    matrix = _read_json(cov / "tp_matrix.json")
    case_tp = _read_json(cov / "case_tp.json")
    case_ir = _read_json(cov / "case_ir.json")

    rows = {str(r.get("tp_id") or ""): r for r in matrix.get("rows") or []
            if isinstance(r, dict)}
    by_tp = (case_tp.get("by_tp") or {}) if isinstance(case_tp, dict) else {}
    cells = _accumulate(evidence, rows, by_tp)
    _merge_evidence(cells, _evidence_by_cell(root))
    out_cells = _finalize(cells)

    counts = {c: sum(1 for x in out_cells if x["color"] == c)
              for c in (COLOR_GREEN, COLOR_YELLOW, COLOR_RED, COLOR_NA)}
    return {
        "schema": SCHEMA,
        "run": root.name,
        "rule": "CELL = CELL-<CG>-<P>；CG=TP IR dimension，P=execution.stage",
        "counts": {**counts, "total": len(out_cells)},
        "cases_declared": (case_ir.get("cases") or []),
        "cells": out_cells,
        "sources": {
            "tp_cov_evidence": bool(evidence),
            "tp_matrix": bool(matrix),
            "case_tp": bool(case_tp),
            "case_ir": bool(case_ir),
        },
        "notes": ([] if out_cells else ["没有可聚合的 TP 证据（先跑一轮覆盖率）"]),
    }


def write_cell_matrix(od: str | Path) -> Dict[str, Any]:
    """把矩阵落到 `coverage/cell_matrix.json`（生成物，PR 禁止手改）。"""
    data = build_cell_matrix(od)
    path = Path(od) / "coverage" / "cell_matrix.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        pass
    return data


__all__ = [
    "SCHEMA", "COLOR_GREEN", "COLOR_YELLOW", "COLOR_RED", "COLOR_NA",
    "build_cell_matrix", "cell_color", "cell_id_of", "write_cell_matrix",
]
