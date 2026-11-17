"""三种投影视图 —— 只读，不改变实体状态或证据。"""
from __future__ import annotations

from typing import Any, Dict, List

from .schema import EntityType, UnifiedIR

_MENTAL = (
    EntityType.GOAL, EntityType.ASSUMPTION, EntityType.AMBIGUITY,
    EntityType.VERIFICATION_INTENT, EntityType.RISK,
)
_DPLAN = (
    EntityType.MODULE, EntityType.PORT, EntityType.REGISTER,
    EntityType.FEATURE, EntityType.BEHAVIOR, EntityType.MODEL_STATE,
)
_VPLAN = (
    EntityType.REQUIREMENT, EntityType.CONTRACT,
    EntityType.TESTPOINT, EntityType.CASE,
)


def _collect(ir: UnifiedIR, types) -> List[Dict[str, Any]]:
    wanted = {t.value for t in types}
    return [
        {
            "id": entity.id,
            "type": entity.entity_type,
            "native_id": entity.key.native_id,
            "source": entity.source,
            "status": entity.status,
            "payload": entity.payload,
        }
        for entity in sorted(ir.entities, key=lambda e: e.id)
        if entity.entity_type in wanted
    ]


def mental_view(ir: UnifiedIR) -> Dict[str, Any]:
    return {"mode": ir.mode, "items": _collect(ir, _MENTAL)}


def dplan_view(ir: UnifiedIR) -> Dict[str, Any]:
    return {"mode": ir.mode, "items": _collect(ir, _DPLAN)}


def vplan_view(ir: UnifiedIR) -> Dict[str, Any]:
    return {"mode": ir.mode, "items": _collect(ir, _VPLAN)}


def views(ir: UnifiedIR) -> Dict[str, Any]:
    return {
        "mental": mental_view(ir),
        "dplan": dplan_view(ir),
        "vplan": vplan_view(ir),
        "summary": ir.summary(),
    }


__all__ = ["mental_view", "dplan_view", "vplan_view", "views"]
