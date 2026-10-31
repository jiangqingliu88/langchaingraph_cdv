"""优化回归前后对比（`regression_optimize_result_v1`）。"""
from __future__ import annotations

from typing import Any, Dict, List


def _tasks(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for task in (report or {}).get("tasks") or []:
        if not isinstance(task, dict):
            continue
        name = str(task.get("name") or task.get("work_dir") or "")
        if name.startswith("test_"):
            name = name[5:]
        if name:
            out[name] = task
    return out


def compare_reports(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    b = _tasks(before)
    a = _tasks(after)
    common = sorted(set(b) & set(a))
    status_delta = {n: {"before": b[n].get("status"), "after": a[n].get("status")}
                    for n in common
                    if b[n].get("status") != a[n].get("status")}
    before_s = sum(float(t.get("elapsed") or 0) for t in b.values())
    after_s = sum(float(t.get("elapsed") or 0) for t in a.values())
    return {
        "schema": "regression_optimize_result_v1",
        "before_tests": len(b),
        "after_tests": len(a),
        "removed_tests": sorted(set(b) - set(a)),
        "added_tests": sorted(set(a) - set(b)),
        "status_changes": status_delta,
        "elapsed_seconds": {"before": round(before_s, 2), "after": round(after_s, 2),
                            "saved": round(max(0.0, before_s - after_s), 2),
                            "saved_pct": round(max(0.0, before_s - after_s) / before_s * 100, 2)
                            if before_s else 0.0},
        "notes": ["removed_tests 是优化计划跳过的用例；status_changes 必须为空才算安全"],
    }
