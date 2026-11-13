"""统一验证义务模型 —— 比 `TP_MISSED` 更准确地表达“还欠什么证据”。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ObligationStatus(str, Enum):
    OPEN = "OPEN"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    PARTIAL = "PARTIAL"
    PROVEN = "PROVEN"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    WAIVED = "WAIVED"


#: 终态 / 非终态
TERMINAL = frozenset({ObligationStatus.PROVEN, ObligationStatus.FAILED,
                      ObligationStatus.WAIVED})
DONE = frozenset({ObligationStatus.PROVEN, ObligationStatus.WAIVED})


@dataclass
class VerificationObligation:
    obligation_id: str
    source_type: str = ""
    source_id: str = ""
    tp_id: Optional[str] = None
    case_id: Optional[str] = None
    obligation_type: str = ""
    required_conditions: List[str] = field(default_factory=list)
    required_evidence: List[str] = field(default_factory=list)
    priority: str = ""
    status: str = ObligationStatus.OPEN.value
    reasons: List[str] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.status in {s.value for s in DONE}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def from_contract_obligation(ob: Any, *, status: str,
                             case_id: str = "", tp_id: str = "",
                             reasons: List[str] = None) -> VerificationObligation:
    """现有 `contract_model.Obligation` → 统一义务。"""
    kind = str(getattr(ob, "kind", "") or "")
    evidence = {
        "group_layer": ["functional", "timing", "data", "path"],
        "sva": ["sva_hit", "non_vacuous"],
        "scb": ["scb_executed", "mismatched_zero"],
    }.get(kind, [])
    subject = dict(getattr(ob, "subject", {}) or {})
    return VerificationObligation(
        obligation_id=str(getattr(ob, "obligation_id", "") or ""),
        source_type="contract_obligation",
        source_id=str(getattr(ob, "contract_id", "") or ""),
        tp_id=tp_id or None,
        case_id=case_id or str(getattr(ob, "case", "") or ""),
        obligation_type=kind,
        required_conditions=list((getattr(ob, "predicate", None)
                                  and getattr(ob.predicate, "where", {}) or {}
                                  ).keys()),
        required_evidence=evidence,
        priority=str(subject.get("priority") or ""),
        status=status,
        reasons=list(reasons or []),
    )


__all__ = [
    "DONE", "TERMINAL", "ObligationStatus", "VerificationObligation",
    "from_contract_obligation",
]
