"""自主闭环的动作候选：从义务/覆盖缺口到确定性动作列表。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class ActionCandidate:
    action: str
    source: str                 # obligation | coverage_hole | worklist
    target: str
    priority: str = ""
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def from_obligations(obligations: List[Any]) -> List[ActionCandidate]:
    from src.layers.l3_decision.obligation import actions_for

    out: List[ActionCandidate] = []
    for ob in obligations:
        for action in actions_for(ob):
            out.append(ActionCandidate(
                action=action, source="obligation",
                target=str(getattr(ob, "obligation_id", "") or ""),
                priority=str(getattr(ob, "priority", "") or ""),
                reason=str(getattr(ob, "status", "") or ""),
                payload={"case_id": getattr(ob, "case_id", ""),
                         "tp_id": getattr(ob, "tp_id", "")},
            ))
    return out


def from_coverage_holes(holes: Dict[str, Any]) -> List[ActionCandidate]:
    mapping = {
        "stimulus_gap": "GENERATE_DIRECTED_TEST",
        "model_drift": "FIX_MODEL_OR_NAMING",
        "signoff_gap": "ADD_EVIDENCE",
        "backend_pending": "WAIT_BACKEND",
    }
    out: List[ActionCandidate] = []
    for hole in (holes or {}).get("holes") or []:
        if not isinstance(hole, dict):
            continue
        action = mapping.get(str(hole.get("action") or ""),
                             "ANALYZE_GAP")
        out.append(ActionCandidate(
            action=action, source="coverage_hole",
            target=str(hole.get("tp_id") or ""),
            reason=str(hole.get("action") or ""),
            payload={"dimension": hole.get("dimension", ""),
                     "bin": hole.get("bin", ""),
                     "owner_test": hole.get("owner_test", ""),
                     "seeds": list(hole.get("seeds") or [])},
        ))
    return out


def any_candidates(obligations: List[Any], holes: Dict[str, Any]
                   ) -> List[ActionCandidate]:
    return from_obligations(obligations) + from_coverage_holes(holes)


__all__ = [
    "ActionCandidate", "any_candidates", "from_coverage_holes",
    "from_obligations",
]
