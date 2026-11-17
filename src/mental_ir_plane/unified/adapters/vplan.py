"""VPlan 快照 → 统一 IR 实体（验证义务投影）。

接受 dict，或任何带 `requirements / features / contracts / testpoints / cases`
属性的对象（如 `VPlanProject`），不 import VPlan 引擎，避免 IR 反向依赖执行层。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..normalize import safe_id, split_ids
from ..schema import (
    Entity,
    EntityKey,
    EntityType,
    Issue,
    IssueSeverity,
    Relation,
    RelationKind,
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _rows(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, dict):
        out = []
        for key, row in value.items():
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item.setdefault("id", key)
            out.append(item)
        return out
    if isinstance(value, (list, tuple)):
        return [row for row in value if isinstance(row, dict)]
    return []


def import_vplan(project: Any, *, project_id: str,
                 artifact_id: str = "") -> Tuple[List[Entity], List[Relation], List[Issue], Dict[str, Any]]:
    entities: List[Entity] = []
    relations: List[Relation] = []
    issues: List[Issue] = []
    source = artifact_id or "vplan"

    def add(entity_type: EntityType, native: Any, payload: Dict[str, Any]) -> Entity:
        entity = Entity(
            key=EntityKey(project_id=project_id, entity_type=entity_type.value,
                          native_id=safe_id(native, fallback=entity_type.value),
                          revision="vplan"),
            payload=payload,
            source=source,
            status="imported",
        )
        entities.append(entity)
        return entity

    features = _rows(_get(project, "features"))
    requirements = _rows(_get(project, "requirements"))
    contracts = _rows(_get(project, "contracts"))
    testpoints = _rows(_get(project, "testpoints"))
    cases = _rows(_get(project, "cases"))

    for row in features:
        add(EntityType.FEATURE, row.get("feature_id") or row.get("id") or row.get("name"), row)
    for row in requirements:
        req = add(EntityType.REQUIREMENT, row.get("req_id") or row.get("id"), row)
        for feature_id in split_ids(row.get("feature_ids") or row.get("features")):
            relations.append(Relation(
                source=req.id,
                target=EntityKey(project_id=project_id, entity_type=EntityType.FEATURE.value,
                                 native_id=safe_id(feature_id), revision="vplan").id,
                kind=RelationKind.REFERENCES.value,
                status="confirmed", evidence="requirement.feature_ids", artifact_id=source,
            ))
    for row in contracts:
        add(EntityType.CONTRACT, row.get("contract_id") or row.get("id"), row)
    for row in testpoints:
        tp = add(EntityType.TESTPOINT, row.get("tp_id") or row.get("id"), row)
        for contract_id in split_ids(row.get("contract_ids") or row.get("contracts")):
            relations.append(Relation(
                source=tp.id,
                target=EntityKey(project_id=project_id, entity_type=EntityType.CONTRACT.value,
                                 native_id=safe_id(contract_id), revision="vplan").id,
                kind=RelationKind.REFERENCES.value,
                status="confirmed", evidence="testpoint.contract_ids", artifact_id=source,
            ))
    for row in cases:
        case = add(EntityType.CASE, row.get("case_id") or row.get("id"), row)
        for tp_id in split_ids(row.get("tp_ids") or row.get("testpoints")):
            relations.append(Relation(
                source=case.id,
                target=EntityKey(project_id=project_id, entity_type=EntityType.TESTPOINT.value,
                                 native_id=safe_id(tp_id), revision="vplan").id,
                kind=RelationKind.REFERENCES.value,
                status="confirmed", evidence="case.tp_ids", artifact_id=source,
            ))

    for warning in (_get(project, "warnings") or []):
        issues.append(Issue(
            issue_id=f"issue:vplan_warning:{project_id}:{safe_id(warning)[:48]}",
            kind="vplan_loader_warning",
            message=str(warning),
            severity=IssueSeverity.WARNING.value,
            refs=[source],
        ))

    counts = {
        "module": str(_get(project, "module") or _get(project, "dut") or ""),
        "requirements": len(requirements),
        "features": len(features),
        "contracts": len(contracts),
        "testpoints": len(testpoints),
        "cases": len(cases),
    }
    return entities, relations, issues, {
        "version": str(_get(project, "schema_version") or "vplan_project"),
        "loader": "vplan_snapshot",
        "counts": counts,
    }
