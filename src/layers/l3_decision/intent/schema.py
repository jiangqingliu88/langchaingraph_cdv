"""验证意图模型 —— 语义映射先是**候选假设**，确认后才进契约。

    Requirement / spec / xlsx
              │
              ▼
      VerificationIntent (CANDIDATE)
              │  EDA 校验 或 人工审批
              ▼
        CONFIRMED / REJECTED（保留，作为“为什么没这么测”的证据）

`intent_id` 从内容哈希生成；改一条 goal 就换一个 id —— 意图不是可随意
覆盖的草稿，而是可引用的证据对象。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

SCHEMA = "verification_intent_v1"


class IntentStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


def canonical_hash(doc: Any) -> str:
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class IntentGoal:
    kind: str                    # dimension | coverage | assertion | checker | evidence
    target: str
    rationale: str = ""


@dataclass
class Assumption:
    text: str
    status: str = "OPEN"         # OPEN | CONFIRMED | REJECTED
    evidence_ids: List[str] = field(default_factory=list)


@dataclass
class VerificationIntent:
    case_id: str
    statement: str = ""
    module: str = ""
    source: str = ""             # spec | xlsx | human | case_model | synthesized
    source_span: str = ""
    goals: List[IntentGoal] = field(default_factory=list)
    assumptions: List[Assumption] = field(default_factory=list)
    status: str = IntentStatus.CANDIDATE.value
    confirmed_by: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0
    intent_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        body = asdict(self)
        body["schema"] = SCHEMA
        return body

    def compute_hash(self) -> str:
        body = self.to_dict()
        body.pop("intent_id", None)
        return canonical_hash(body)

    def seal(self) -> "VerificationIntent":
        self.intent_id = f"INT-{self.compute_hash()[:12]}"
        return self

    @property
    def confirmed(self) -> bool:
        return self.status == IntentStatus.CONFIRMED.value


def from_dict(doc: Dict[str, Any]) -> VerificationIntent:
    doc = doc or {}
    return VerificationIntent(
        case_id=str(doc.get("case_id") or ""),
        statement=str(doc.get("statement") or ""),
        module=str(doc.get("module") or ""),
        source=str(doc.get("source") or ""),
        source_span=str(doc.get("source_span") or ""),
        goals=[IntentGoal(**g) for g in (doc.get("goals") or [])
               if isinstance(g, dict) and g.get("kind")],
        assumptions=[Assumption(**a) for a in (doc.get("assumptions") or [])
                     if isinstance(a, dict) and a.get("text")],
        status=str(doc.get("status") or IntentStatus.CANDIDATE.value),
        confirmed_by=str(doc.get("confirmed_by") or ""),
        evidence_ids=[str(e) for e in (doc.get("evidence_ids") or []) if str(e)],
        confidence=float(doc.get("confidence") or 0.0),
        intent_id=str(doc.get("intent_id") or ""),
        metadata=dict(doc.get("metadata") or {}),
    )


__all__ = [
    "SCHEMA", "Assumption", "IntentGoal", "IntentStatus", "VerificationIntent",
    "canonical_hash", "from_dict",
]
