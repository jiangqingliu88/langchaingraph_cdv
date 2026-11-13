"""三份真相的同源校验：TP IR ↔ StimulusPlan ↔ constraint_backing。

产物：`coverage/plan_consistency.json`

检查：
  1. plan 里的 `tp_id` 必须在 `testpoints.json` 存在，且 realization kind 一致；
  2. plan 事务字段必须能在一个 **backed** 约束里找到对应维度，否则显式记
     `unconstrained`（是事实，不是失败）；
  3. `constraint_backing` 里 backed 的策略维度必须至少被一个 plan 条目引用，
     否则记 `dangling_constraint`（说明约束在约束一个没人激励的东西）。

`issues` 非空时 audit 会挂 `PLAN_INCONSISTENT` caveat。纯读 + 写一个 JSON。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

SCHEMA = "plan_consistency_v1"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:                               # noqa: BLE001
        return {}
    return doc if isinstance(doc, dict) else {}


def _canon(doc: Dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str)


def _check_entry(entry: Dict[str, Any], tp_by_id: Dict[str, Dict[str, Any]],
                 policies: List[Dict[str, Any]], issues: List[Dict[str, Any]],
                 unconstrained: List[Dict[str, Any]], used_dims: set) -> None:
    tp_id = str(entry.get("tp_id") or "")
    tp = tp_by_id.get(tp_id)
    if tp is None:
        issues.append({"type": "tp_missing", "tp_id": tp_id})
        return
    tp_kind = str((tp.get("realization") or {}).get("kind") or "")
    if str(entry.get("kind") or "") != tp_kind:
        issues.append({"type": "kind_mismatch", "tp_id": tp_id,
                       "plan": entry.get("kind"), "testpoints": tp_kind})
    dim = str(tp.get("dimension") or "")
    used_dims.add(dim)
    backed = [p for p in policies
              if p.get("backed") and dim in (p.get("dimensions") or [])]
    for tx in entry.get("transactions") or []:
        field = str((tx or {}).get("field") or "")
        if field and not backed:
            unconstrained.append({"tp_id": tp_id, "dimension": dim,
                                  "field": field,
                                  "note": "没有 backed 约束覆盖该维度"})


def _check_dangling(policies: List[Dict[str, Any]], used_dims: set,
                    issues: List[Dict[str, Any]]) -> None:
    for policy in policies:
        if not policy.get("backed"):
            continue
        for dim in policy.get("dimensions") or []:
            if str(dim) not in used_dims:
                issues.append({"type": "dangling_constraint",
                               "policy": policy.get("name", ""),
                               "dimension": str(dim),
                               "note": "约束在约束一个没有被 plan 引用的维度"})


def _check_unplanned(tp_by_id: Dict[str, Dict[str, Any]], entries,
                     unsupported, issues: List[Dict[str, Any]]) -> None:
    planned_ids = {str(e.get("tp_id") or "") for e in entries}
    unsupported_ids = {str(u.get("tp_id") or "") for u in unsupported}
    for tp_id, tp in tp_by_id.items():
        kind = str((tp.get("realization") or {}).get("kind") or "")
        if kind in ("stimulus", "sequence", "backdoor") \
                and tp_id not in planned_ids and tp_id not in unsupported_ids:
            issues.append({"type": "tp_unplanned", "tp_id": tp_id, "kind": kind})


def build_plan_consistency(output_dir: str | Path) -> Dict[str, Any]:
    root = Path(output_dir)
    testpoints = _read_json(root / "coverage" / "testpoints.json").get("testpoints") or []
    plan = _read_json(root / "coverage" / "stimulus_plan.json")
    coverage_plan = _read_yaml(root / "coverage" / "coverage_plan.yaml")
    policies = ((coverage_plan.get("constraint_backing") or {}).get("policies") or [])

    tp_by_id = {str(t.get("tp_id") or ""): t for t in testpoints
                if isinstance(t, dict)}
    entries = [e for e in (plan.get("testpoints") or []) if isinstance(e, dict)]

    issues: List[Dict[str, Any]] = []
    unconstrained: List[Dict[str, Any]] = []
    used_dims: set = set()
    for entry in entries:
        _check_entry(entry, tp_by_id, policies, issues, unconstrained, used_dims)
    _check_dangling(policies, used_dims, issues)
    _check_unplanned(tp_by_id, entries, plan.get("unsupported") or [], issues)

    result = {
        "schema": SCHEMA,
        "plan_sha256": plan.get("sha256", ""),
        "backend": plan.get("backend", ""),
        "counts": {
            "testpoints": len(tp_by_id),
            "planned": len(entries),
            "unconstrained": len(unconstrained),
            "issues": len(issues),
        },
        "issues": issues,
        "unconstrained": unconstrained,
    }
    result["sha256"] = hashlib.sha256(_canon(result).encode("utf-8")).hexdigest()
    return result


def write_plan_consistency(output_dir: str | Path,
                           report: Dict[str, Any] = None) -> Dict[str, Any]:
    root = Path(output_dir)
    report = report or build_plan_consistency(root)
    path = root / "coverage" / "plan_consistency.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return {"path": str(path), "ok": not report.get("issues"),
            "issues": len(report.get("issues") or []),
            "sha256": report.get("sha256", "")}
