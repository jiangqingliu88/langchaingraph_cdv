"""下一轮上下文 —— 闭环反馈的**唯一入口**（证据 + 未决 + 决策）。

把历史全塞回 prompt 既不可复现也不可审计；这里只聚合结构化读数。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

SCHEMA = "next_iteration_context_v1"


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


def build_next_context(root: str | Path) -> Dict[str, Any]:
    root = Path(root)
    index = _read_json(root / "docs" / "evidence_index.json")
    obligations = _read_json(root / "docs" / "obligations_v3.json")
    holes = _read_json(root / "coverage" / "coverage_holes.json")
    closure = _read_json(root / "status" / "closure_plan.json")
    interps = _read_json(root / "status" / "interpretations.json")

    open_obs = [o for o in (obligations.get("obligations") or [])
                if isinstance(o, dict)
                and str(o.get("status") or "") not in ("PROVEN", "WAIVED")]
    rejected = [i for i in (interps.get("items") or [])
                if isinstance(i, dict) and i.get("status") == "REJECTED"]
    body = {
        "schema": SCHEMA,
        "evidence": {"ledger": index.get("ledger") or {},
                     "claim_counts": index.get("claim_counts") or {},
                     "claims_without_evidence":
                         (index.get("claims_without_evidence") or [])[:50]},
        "open_obligations": [
            {"obligation_id": o.get("obligation_id"),
             "case_id": o.get("case_id"), "tp_id": o.get("tp_id"),
             "status": o.get("status"), "reasons": o.get("reasons") or []}
            for o in open_obs[:50]
        ],
        "coverage_holes": (holes.get("holes") or [])[:50],
        "rejected_interpretations": rejected[:20],
        "approved_actions": [
            a for a in (closure.get("actions") or [])[:20]
            if isinstance(a, dict)
        ],
        "notes": [] if open_obs or holes.get("holes") else
                 ["没有未决义务与覆盖缺口 —— 下一轮可考虑收敛"],
    }
    body["context_hash"] = _digest(body)
    path = root / "status" / "next_iteration_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return {"available": True, "path": "status/next_iteration_context.json",
            "open_obligations": len(body["open_obligations"]),
            "holes": len(body["coverage_holes"]),
            "claims_without_evidence":
                len(body["evidence"]["claims_without_evidence"]),
            "context_hash": body["context_hash"]}


__all__ = ["SCHEMA", "build_next_context"]
