"""Mental IR → 统一 IR 实体（理解层投影）。

Mental IR 是候选理解，不是执行事实；这里只把结构化条目原样搬进对象图。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ...model import MentalIR
from ..normalize import safe_id
from ..schema import (
    Entity,
    EntityKey,
    EntityType,
    Issue,
    IssueSeverity,
    Relation,
    RelationKind,
)


def import_mental(mental: MentalIR | Dict[str, Any], *,
                  project_id: str, artifact_id: str = "") -> Tuple[List[Entity], List[Relation], List[Issue], Dict[str, Any]]:
    ir = mental if isinstance(mental, MentalIR) else MentalIR.model_validate(mental)
    entities: List[Entity] = []
    relations: List[Relation] = []
    issues: List[Issue] = []

    def add(entity_type: EntityType, native_id: str, payload: Dict[str, Any]) -> Entity:
        entity = Entity(
            key=EntityKey(project_id=project_id, entity_type=entity_type.value,
                          native_id=safe_id(native_id, fallback=entity_type.value),
                          revision="mental"),
            payload=payload,
            source=artifact_id or "mental_ir",
            status="candidate",
        )
        entities.append(entity)
        return entity

    for item in ir.goals:
        add(EntityType.GOAL, item.id, item.model_dump(mode="json"))
    for item in ir.assumptions:
        add(EntityType.ASSUMPTION, item.id, item.model_dump(mode="json"))
    for item in ir.ambiguities:
        add(EntityType.AMBIGUITY, item.id, item.model_dump(mode="json"))
        if item.blocking:
            issues.append(Issue(
                issue_id=f"issue:blocking_ambiguity:{project_id}:{item.id}",
                kind="blocking_ambiguity",
                message=f"{item.id}: {item.question}",
                severity=IssueSeverity.WARNING.value,
                blocking=True,
                refs=[f"{project_id}:{EntityType.AMBIGUITY.value}:{safe_id(item.id)}"],
            ))
    for item in ir.verification_intents:
        add(EntityType.VERIFICATION_INTENT, item.id, item.model_dump(mode="json"))
    for item in ir.risks:
        add(EntityType.RISK, item.id, item.model_dump(mode="json"))

    # intent → goal 的显式引用
    for item in ir.verification_intents:
        source = EntityKey(project_id=project_id, entity_type=EntityType.VERIFICATION_INTENT.value,
                           native_id=safe_id(item.id), revision="mental").id
        for goal_id in item.goal_ids:
            target = EntityKey(project_id=project_id, entity_type=EntityType.GOAL.value,
                               native_id=safe_id(goal_id), revision="mental").id
            relations.append(Relation(
                source=source, target=target, kind=RelationKind.REFERENCES.value,
                status="confirmed", evidence="mental verification_intent.goal_ids",
                artifact_id=artifact_id,
            ))

    counts = ir.counts()
    return entities, relations, issues, {
        "version": ir.schema_version,
        "loader": "mental_ir_plane.model.MentalIR",
        "counts": counts,
    }
