"""Claim —— 智能体/人声称的结论，以及它需要的证据种类。

    Claim（statement + evidence_required）
              │
              ▼
    Evidence Store（引擎观测 / 人工决定 / 可重放派生）
              │
              ▼
    CONFIRMED（有证据） / CANDIDATE（还没有）

Claim 不是事实；它是“需要被证明的那句话”。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

SCHEMA = "claim_v1"
STATUSES = ("CANDIDATE", "CONFIRMED", "REJECTED")


def canonical_hash(doc: Any) -> str:
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Claim:
    statement: str
    case_id: str = ""
    intent_id: str = ""
    kind: str = ""                # dimension | coverage | assertion | checker | evidence
    subject: Dict[str, Any] = field(default_factory=dict)
    evidence_required: List[str] = field(default_factory=list)
    status: str = "CANDIDATE"
    producer_class: str = "agent"  # engine | human | agent
    obligation_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    claim_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA}

    def compute_hash(self) -> str:
        body = self.to_dict()
        body.pop("claim_id", None)
        return canonical_hash(body)

    def seal(self) -> "Claim":
        self.claim_id = f"CLM-{self.compute_hash()[:12]}"
        return self

    @property
    def confirmed(self) -> bool:
        return self.status == "CONFIRMED"


def from_dict(doc: Dict[str, Any]) -> Claim:
    doc = doc or {}
    return Claim(
        statement=str(doc.get("statement") or ""),
        case_id=str(doc.get("case_id") or ""),
        intent_id=str(doc.get("intent_id") or ""),
        kind=str(doc.get("kind") or ""),
        subject=dict(doc.get("subject") or {}),
        evidence_required=[str(e) for e in (doc.get("evidence_required") or []) if str(e)],
        status=str(doc.get("status") or "CANDIDATE"),
        producer_class=str(doc.get("producer_class") or "agent"),
        obligation_ids=[str(o) for o in (doc.get("obligation_ids") or []) if str(o)],
        evidence_ids=[str(e) for e in (doc.get("evidence_ids") or []) if str(e)],
        claim_id=str(doc.get("claim_id") or ""),
    )


__all__ = ["SCHEMA", "STATUSES", "Claim", "canonical_hash", "from_dict"]
