"""EVD —— **一次执行的证据身份**（去重键 `(run, tst, seed, cfg)`）。

`case_cov/<stage>/<task>.json` 本来就是一次执行的证据；它缺的只是**身份**：
没有 `run_id` / `evd_id` / `tst_id`，跨 run 去重、版本过期、失败分类都只能
拿目录名当键。本模块把身份补上，并把同一 `(tst, seed, cfg)` 的重复执行收敛成
一条 EVD（重跑不新增身份，只刷新 `last_seen`）。

旧 run（`legacy`：没有 `case_id`）照样**可读**，但不参与新版本聚合 ——
标 `legacy: true`，视图里能看见，门禁不会把它当“已验证”。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.tools.humanview.case_ir import evd_id_of, tst_id_of

SCHEMA = "evd_v1"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _case_records(od: Path) -> List[Dict[str, Any]]:
    """`coverage/case_cov/**/*.json`（`.json.cache` 不算——那是缓存）。"""
    out: List[Dict[str, Any]] = []
    for path in sorted((od / "coverage" / "case_cov").rglob("*.json")):
        if path.name.endswith(".cache"):
            continue
        rec = _read_json(path)
        if rec.get("task"):
            rec.setdefault("_path", str(path))
            out.append(rec)
    return out


def _cell_index(od: Path) -> Dict[str, str]:
    """`tp_id → cell_id`（来自 cell_matrix；没有就是空表）。"""
    matrix = _read_json(od / "coverage" / "cell_matrix.json")
    index: Dict[str, str] = {}
    for cell in matrix.get("cells") or []:
        for tp in cell.get("tps") or []:
            tid = str(tp.get("tp_id") or "")
            if tid:
                index[tid] = str(cell.get("cell_id") or "")
    return index


def _checker_rows(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """一条用例的控制项 → 逐 checker 的行（group / sva / scb）。

    去重键要**扩到 checker 级**：同一条 case 的多个组 / 多条 SVA / 多个 SB
    如果共用一条 EVD，后写的会把先写的覆盖掉（arch.md §7）。
    """
    rows: List[Dict[str, Any]] = []
    for item in rec.get("groups") or []:
        if isinstance(item, dict) and item.get("group"):
            rows.append({"checker_type": "group",
                         "checker_id": str(item["group"]),
                         "cell": str(item.get("cell") or ""),
                         "status": str(item.get("result") or ""),
                         "detail": {k: (item.get(k) or {}).get("status", "")
                                    for k in ("functional", "timing", "data", "path")}})
    for item in rec.get("sva") or []:
        if isinstance(item, dict) and item.get("id"):
            rows.append({"checker_type": "sva", "checker_id": str(item["id"]),
                         "cell": str(item.get("cell") or ""),
                         "status": str(item.get("status") or ""),
                         "detail": {"fail": item.get("fail", 0)}})
    for item in rec.get("scb") or []:
        if isinstance(item, dict) and item.get("id"):
            rows.append({"checker_type": "scb", "checker_id": str(item["id"]),
                         "cell": str(item.get("cell") or ""),
                         "status": str(item.get("status") or ""),
                         "detail": {"matched": item.get("matched"),
                                    "mismatched": item.get("mismatched"),
                                    "exec": item.get("exec", 0)}})
    return rows


def _evd_common(rec: Dict[str, Any], run_id: str,
                cell_of: Dict[str, str]) -> tuple:
    """`(base_evd_id, common_fields)` —— 每次执行只算一次。"""
    test = str(rec.get("test") or rec.get("test_name") or "")
    seed = rec.get("seed")
    tst = str(rec.get("tst_id") or tst_id_of(test, seed))
    case_id = str(rec.get("case_id") or "")
    tp_ids = [str(t.get("tp_id") or "") for t in rec.get("tp") or []
              if isinstance(t, dict) and t.get("tp_id")]
    common = {
        "run_id": run_id, "tst_id": tst, "case_id": case_id, "test": test,
        "seed": seed, "cfg": str(rec.get("cfg") or rec.get("config") or ""),
        "stage": str(rec.get("stage") or ""), "task": str(rec.get("task") or ""),
        "tp_ids": tp_ids,
        "cells": sorted({cell_of[t] for t in tp_ids if t in cell_of}),
        "wave": str(rec.get("wave") or ""), "ucdb": str(rec.get("ucdb") or ""),
        "uvm_errors": int(rec.get("uvm_errors") or 0),
        "timing_ok": rec.get("timing_ok"),
        "case_status": str(rec.get("case_status") or ""),
        "legacy": not bool(case_id),
    }
    return str(rec.get("evd_id") or evd_id_of(run_id, test, seed)), common


def _evd_rows(rec: Dict[str, Any], run_id: str,
              cell_of: Dict[str, str]) -> List[Dict[str, Any]]:
    """一次执行 → 一条 case 级 EVD + 每个 checker 一条 EVD。"""
    base_id, common = _evd_common(rec, run_id, cell_of)
    if not base_id:
        return []
    cells = common["cells"]
    rows = [dict(common, evd_id=base_id, checker_type="case",
                 checker_id=common["case_id"] or common["tst_id"],
                 status=common["case_status"], detail={})]
    for item in _checker_rows(rec):
        rows.append(dict(
            common,
            evd_id=f"{base_id}#{item['checker_type']}:{item['checker_id']}",
            checker_type=item["checker_type"], checker_id=item["checker_id"],
            status=item["status"], detail=item["detail"],
            cells=sorted(set(cells) | ({item["cell"]} if item["cell"] else set()))))
    return rows


def build_evd(od: str | Path) -> Dict[str, Any]:
    """run 的 `case_cov` + `cell_matrix` → `evd_v1`（checker 级去重）。"""
    root = Path(od)
    run_id = str((_read_json(root / "coverage" / "case_tp.json").get("run")
                  or "") or root.name)
    cell_of = _cell_index(root)

    records: Dict[tuple, Dict[str, Any]] = {}
    duplicates = 0
    for rec in _case_records(root):
        for evd in _evd_rows(rec, run_id, cell_of):
            key = (evd["case_id"], evd["seed"], evd["cfg"],
                   evd["checker_type"], evd["checker_id"])
            if key in records:
                duplicates += 1
                keep = records[key]
                keep["runs"] = sorted(set(keep.get("runs") or []) | {evd["task"]})
                continue
            evd["runs"] = [evd["task"]]
            records[key] = evd

    items = sorted(records.values(),
                   key=lambda e: (e["tst_id"], str(e["seed"]),
                                  e["checker_type"], e["checker_id"]))
    return {
        "schema": SCHEMA,
        "run": run_id,
        "counts": {
            "total": len(items),
            "cases": len({e["evd_id"].split("#")[0] for e in items}),
            "legacy": sum(1 for e in items if e["legacy"]),
            "with_case": sum(1 for e in items if e["case_id"]),
            "with_cells": sum(1 for e in items if e["cells"]),
            "by_checker": {t: sum(1 for e in items if e["checker_type"] == t)
                           for t in ("case", "group", "sva", "scb")},
            "duplicates_collapsed": duplicates,
        },
        "evd": items,
        "notes": ([] if items else ["没有 case_cov 记录（先跑一轮覆盖率）"]),
    }


def write_evd(od: str | Path) -> Dict[str, Any]:
    data = build_evd(od)
    path = Path(od) / "coverage" / "evd.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        pass
    return data


__all__ = ["SCHEMA", "build_evd", "write_evd"]
