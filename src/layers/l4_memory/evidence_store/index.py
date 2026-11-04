"""证据索引 —— `docs/evidence_index.json`（ledger 的可重建索引 + claim 覆盖）。

**不是第二份事实**：ledger 是唯一事实源，本文件只是查询缓存/读数。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .kinds import SCHEMA
from .query import counts, evidence_for_claims, read_ledger


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def _jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        try:
            rec = json.loads(line) if line.strip() else {}
        except ValueError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def build_evidence_index(root: str | Path) -> Dict[str, Any]:
    root = Path(root)
    ledger = read_ledger(root)
    claims_doc = _read_json(root / "coverage" / "claims.json")
    claims = [c for c in (claims_doc.get("claims") or [])
              if isinstance(c, dict) and c.get("claim_id")]
    by_claim = evidence_for_claims(ledger)
    claim_rows: List[Dict[str, Any]] = []
    without: List[str] = []
    for claim in claims:
        cid = str(claim["claim_id"])
        facts = by_claim.get(cid) or []
        if not facts:
            without.append(cid)
        claim_rows.append({
            "claim_id": cid,
            "status": str(claim.get("status") or "CANDIDATE"),
            "producer_class": str(claim.get("producer_class") or "agent"),
            "evidence_required": list(claim.get("evidence_required") or []),
            "evidence_count": len(facts),
            "evidence_ids": [str(f.get("fact_id") or f.get("hash") or "")[:16]
                             for f in facts[:20]],
        })
    doc = {
        "schema": SCHEMA,
        "ledger": counts(ledger),
        "claims": {row["claim_id"]: {"status": row["status"],
                                     "producer_class": row["producer_class"],
                                     "evidence_ids": row["evidence_ids"],
                                     "evidence_count": row["evidence_count"]}
                   for row in claim_rows},
        "claim_counts": {
            "total": len(claim_rows),
            "with_evidence": sum(1 for r in claim_rows if r["evidence_count"]),
            "without_evidence": len(without),
        },
        "claims_without_evidence": without,
        # Agent 的“解释”也是假设；工程师审批是事实。
        # 老 llm_audit 行没有 fact_class —— 一律按 HYPOTHESIS/agent 计（原则优先）。
        "llm_audit_lines": _count_lines(root / "docs" / "llm_audit.jsonl"),
        "llm_hypotheses": sum(
            1 for r in _jsonl(root / "docs" / "llm_audit.jsonl")
            if str(r.get("fact_class") or "HYPOTHESIS").upper() == "HYPOTHESIS"),
        "llm_claim_ids": sorted({
            str(r.get("claim_id")) for r in _jsonl(root / "docs" / "llm_audit.jsonl")
            if r.get("claim_id")}),
        "tool_receipts": _count_lines(root / "docs" / "tool_receipts.jsonl"),
        "interpretations": len((_read_json(root / "status" /
                                           "interpretations.json")
                                .get("items") or [])),
    }
    path = root / "docs" / "evidence_index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return doc


__all__ = ["build_evidence_index"]
