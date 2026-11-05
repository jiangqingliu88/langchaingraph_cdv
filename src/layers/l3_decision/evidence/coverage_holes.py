"""覆盖缺口 → 该补哪条 test / 哪个 seed（**建议层**，不参与判定）。

大厂 CDV（coverage-driven verification）闭环的关键不是"报告覆盖率"，而是
**把缺口翻译成下一步动作**：

    tp_matrix 的 MISS / UNOBSERVED / UNMAPPED
                 │
                 ▼
    coverage_holes.json：tp × dimension × bin × owner_test × seeds × action

动作只有四类，不编更多：

      stimulus_gap    仓没命中 —— 扩专题/约束，或加 seed
      model_drift     UNMAPPED —— coverpoint/bin 名对不上（先查生成，不是加激励）
      signoff_gap     合并库有命中，但没有单次 seed 同时证明 —— 补波形/seed
      backend_pending 行为/PATH 后端未接

**只读** `coverage/tp_matrix.json` 与 `coverage/testpoints.yaml`，不重算判定。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

SCHEMA = "coverage_holes_v1"
REL_PATH = "coverage/coverage_holes.json"

_STIMULUS = ("MISS", "UNOBSERVED", "BACKDOOR_MISS")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _seeds_by_tp(run_dir: Path) -> Dict[str, List[int]]:
    try:
        import yaml

        doc = yaml.safe_load((run_dir / "coverage" / "testpoints.yaml")
                             .read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, ValueError, ImportError):
        return {}
    out: Dict[str, List[int]] = {}
    for tp in (doc.get("testpoints") if isinstance(doc, dict) else None) or []:
        if not isinstance(tp, dict):
            continue
        tid = str(tp.get("tp_id") or "")
        seeds = (tp.get("execution") or {}).get("seeds") or []
        out[tid] = [int(s) for s in seeds if str(s).isdigit()]
    return out


def _action(row: Dict[str, Any]) -> str:
    status = str(row.get("status") or "")
    if status == "UNMAPPED":
        return "model_drift"
    if status in _STIMULUS:
        return "stimulus_gap"
    if status == "PENDING_BACKEND":
        return "backend_pending"
    return "signoff_gap"


def build_coverage_holes(run_dir: str | Path) -> Dict[str, Any]:
    root = Path(run_dir)
    matrix = _read_json(root / "coverage" / "tp_matrix.json")
    seeds = _seeds_by_tp(root)
    rows: Dict[tuple, Dict[str, Any]] = {}
    for bucket in ("missed", "unmapped", "unsigned"):
        for row in matrix.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            tid = str(row.get("tp_id") or "")
            if not tid:
                continue
            status = str(row.get("status") or "")
            if bucket == "unsigned" and status not in _STIMULUS:
                status = "SIGNED_OFF_GAP"
            action = _action(row) if status != "SIGNED_OFF_GAP" else "signoff_gap"
            key = (tid, status, action)
            if key in rows:
                continue
            rows[key] = {
                "tp_id": tid,
                "dimension": row.get("dimension", ""),
                "value": row.get("value", ""),
                "coverpoint": row.get("coverpoint", ""),
                "bin": row.get("bin", ""),
                "status": status,
                "action": action,
                "owner_test": row.get("owner_test") or row.get("test") or "",
                "seeds": seeds.get(tid, []),
                "stage": row.get("stage", ""),
                "requirement": row.get("requirement", ""),
            }
    holes = sorted(rows.values(),
                   key=lambda r: (r["action"], r["dimension"], r["tp_id"]))
    counts: Dict[str, int] = {}
    for row in holes:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
    return {
        "schema": SCHEMA,
        "run": root.name,
        "available": bool(matrix),
        "counts": {"holes": len(holes), **counts},
        "holes": holes,
        "note": ("建议层：stimulus_gap 先看专题/约束是否覆盖该维度；"
                 "model_drift 先查 coverpoint/bin 命名；signoff_gap 补波形/单 seed 证据"),
    }


def write_coverage_holes(run_dir: str | Path) -> Dict[str, Any]:
    root = Path(run_dir)
    report = build_coverage_holes(root)
    from src.core.runtime.atomic import atomic_write_json

    path = root / REL_PATH
    try:
        atomic_write_json(path, report)
    except OSError:
        pass
    return report


__all__ = ["REL_PATH", "SCHEMA", "build_coverage_holes", "write_coverage_holes"]
