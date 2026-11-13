"""智能体对证据的解释 —— 默认 HYPOTHESIS，工程师复核后才可晋升。

这一层刻意做成**确定性**的：本轮没有 LLM 时，解释来自“未决义务 / 覆盖缺口”
的结构化读数。它不会冒充事实，也不改判定。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

SCHEMA = "interpretations_v1"
_STATUS = ("DRAFT", "REVIEWED", "REJECTED")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _digest(doc: Any) -> str:
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _item(actor: str, insights: List[Dict[str, Any]],
          updates: List[Dict[str, Any]]) -> Dict[str, Any]:
    body = {"actor": actor, "insights": insights, "plan_updates": updates,
            "status": "DRAFT", "fact_class": "HYPOTHESIS"}
    return {"interp_id": f"INT-{_digest(body)[:12]}", **body}


def build_interpretations(root: str | Path) -> Dict[str, Any]:
    root = Path(root)
    obligations = _read_json(root / "docs" / "obligations_v3.json")
    holes = _read_json(root / "coverage" / "coverage_holes.json")
    closure = _read_json(root / "status" / "closure_plan.json")
    insights: List[Dict[str, Any]] = []
    open_obs = [o for o in (obligations.get("obligations") or [])
                if isinstance(o, dict)
                and str(o.get("status") or "OPEN") not in ("PROVEN", "WAIVED")]
    for ob in open_obs[:20]:
        insights.append({
            "claim_id": "",
            "statement": f"义务 {ob.get('obligation_id')} 仍是 {ob.get('status')}",
            "evidence_ids": [],
            "confidence": 0.4,
            "kind": "obligation",
        })
    for hole in (holes.get("holes") or [])[:20]:
        if not isinstance(hole, dict):
            continue
        insights.append({
            "claim_id": "",
            "statement": f"覆盖缺口 {hole.get('tp_id') or hole.get('bin')}："
                         f"{hole.get('action') or 'unknown'}",
            "evidence_ids": [],
            "confidence": 0.5,
            "kind": "coverage_hole",
        })
    updates = [{"action": a.get("action"), "target": a.get("target")}
               for a in (closure.get("actions") or [])[:20] if isinstance(a, dict)]
    items = [] if not (insights or updates) else \
        [_item("agent:signoffai", insights, updates)]
    doc = {"schema": SCHEMA, "statuses": list(_STATUS), "items": items,
           "advisory_only": True}
    path = root / "status" / "interpretations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return {"available": bool(items), "items": len(items),
            "insights": sum(len(i["insights"]) for i in items),
            "plan_updates": sum(len(i["plan_updates"]) for i in items),
            "path": "status/interpretations.json"}


__all__ = ["SCHEMA", "build_interpretations"]
