"""Coverage Closure 计划（`coverage_closure_v1`）。

输入是**已经跑出来的一轮覆盖率**（`tp_matrix.json` / `coverage_result.json`）；
输出是缺口、当前/目标差距、每个缺口的定向动作。这里不跑 EDA、不生成代码 ——
执行由现有闭环（`vagent verify` 链路）承担，避免另造一套引擎。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "coverage_closure_v1"
MISS = {"MISS", "UNOBSERVED", "BACKDOOR_MISS", "UNMAPPED"}


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _action_for(row: Dict[str, Any]) -> str:
    status = str(row.get("status") or "")
    if status == "UNMAPPED":
        return "AUDIT_COVERPOINT"
    if status == "BACKDOOR_MISS":
        return "GENERATE_BACKDOOR_SEQUENCE"
    if bool(row.get("observe_only")):
        return "EXPOSE_OBSERVE_POINT"
    return "GENERATE_DIRECTED_TEST"


def _priority(row: Dict[str, Any]) -> str:
    req = str(row.get("requirement") or "").lower()
    if any(x in req for x in ("must", "shall", "p0", "critical")):
        return "HIGH"
    return "MEDIUM"


def build_closure_plan(run_root: str | Path, target: float = 98.0) -> Dict[str, Any]:
    root = Path(run_root)
    cov = _read_json(root / "sim" / "coverage" / "coverage_result.json")
    matrix = _read_json(root / "coverage" / "tp_matrix.json")
    rows = [r for r in (matrix.get("rows") or []) if isinstance(r, dict)]
    gaps = [r for r in rows if str(r.get("status") or "") in MISS]
    current = _num(cov.get("functional_pct"))
    if current is None:
        current = _num(cov.get("overall_pct"))
    current = current or 0.0
    actions: List[Dict[str, Any]] = []
    for row in gaps:
        actions.append({
            "tp_id": str(row.get("tp_id") or ""),
            "coverpoint": str(row.get("coverpoint") or ""),
            "bin": str(row.get("bin") or ""),
            "status": str(row.get("status") or ""),
            "kind": str(row.get("kind") or ""),
            "requirement": str(row.get("requirement") or ""),
            "action": _action_for(row),
            "reason": "TP 未命中，生成定向激励" if row.get("status") != "UNMAPPED"
                      else "覆盖仓在报告里找不到，先审计模型/覆盖点",
            "priority": _priority(row),
        })
    actions.sort(key=lambda a: (a["priority"] != "HIGH", a["tp_id"]))
    notes: List[str] = []
    if not rows:
        notes.append("没有 tp_matrix rows，缺口不可用（先跑一轮覆盖率）")
    if current >= target:
        notes.append(f"当前覆盖率 {current:.2f}% 已达标 {target:.2f}%")
    return {
        "schema": SCHEMA,
        "run_id": root.name,
        "target": float(target),
        "current_coverage": round(current, 2),
        "gap_to_target": round(max(0.0, target - current), 2),
        "total_bins": len(rows),
        "gap_count": len(gaps),
        "actions": actions,
        "notes": notes,
    }


def write_closure_plan(run_root: str | Path, target: float = 98.0) -> Dict[str, Any]:
    root = Path(run_root)
    plan = build_closure_plan(root, target)
    path = root / "closure" / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    plan["path"] = str(path)
    return plan
