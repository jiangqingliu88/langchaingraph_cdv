"""Claim 落盘 / 读取 —— `coverage/claims.json`。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .compiler import claims_from_intents
from .schema import Claim, from_dict

SCHEMA = "claims_v1"


def write_claims(output_dir: str | Path, intents: List[Any]) -> Dict[str, Any]:
    root = Path(output_dir)
    claims = claims_from_intents(intents)
    counts: Dict[str, int] = {}
    for claim in claims:
        counts[claim.status] = counts.get(claim.status, 0) + 1
    doc = {"schema": SCHEMA, "total": len(claims), "counts": counts,
           "claims": [c.to_dict() for c in claims]}
    path = root / "coverage" / "claims.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return {"path": "coverage/claims.json", "total": len(claims),
            "counts": counts}


def save_claims(output_dir: str | Path, claims: List[Claim]) -> Dict[str, Any]:
    """把（人工审阅后的）claim 列表写回 `coverage/claims.json`。"""
    root = Path(output_dir)
    counts: Dict[str, int] = {}
    for claim in claims:
        counts[claim.status] = counts.get(claim.status, 0) + 1
    doc = {"schema": SCHEMA, "total": len(claims), "counts": counts,
           "claims": [c.to_dict() for c in claims]}
    path = root / "coverage" / "claims.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return {"path": "coverage/claims.json", "total": len(claims),
            "counts": counts}


def load_claims(output_dir: str | Path) -> List[Claim]:
    try:
        doc = json.loads((Path(output_dir) / "coverage" / "claims.json")
                         .read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return []
    return [from_dict(c) for c in (doc.get("claims") or [])
            if isinstance(c, dict)]


__all__ = ["SCHEMA", "load_claims", "save_claims", "write_claims"]
