"""DPlan IR → 统一 IR 实体（实现/模型契约投影）。

输入是 `mental_ir_plane.dplan.DesignPlan`（或原始 JSON）；本层只做对象图映射，
不在统一层重新校验或补造内容。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ...dplan import DesignPlan, validate
from ..normalize import find_garble, safe_id
from ..schema import (
    Entity,
    EntityKey,
    EntityType,
    Issue,
    IssueSeverity,
    Relation,
    RelationKind,
)


def _payload(value: Any) -> Dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    from dataclasses import asdict

    return asdict(value)


def import_dplan(dplan: DesignPlan | Dict[str, Any], *, project_id: str,
                 artifact_id: str = "") -> Tuple[List[Entity], List[Relation], List[Issue], Dict[str, Any]]:
    plan = dplan if isinstance(dplan, DesignPlan) else DesignPlan.from_dict(dplan)
    entities: List[Entity] = []
    relations: List[Relation] = []
    issues: List[Issue] = []
    source = artifact_id or "dplan"
    seen: Dict[str, Entity] = {}
    duplicate_keys = 0
    garbled = 0

    def add(entity_type: EntityType, native: Any, payload: Dict[str, Any]) -> Entity:
        nonlocal garbled, duplicate_keys
        garbled += sum(find_garble(v) for v in payload.values())
        entity = Entity(
            key=EntityKey(project_id=project_id, entity_type=entity_type.value,
                          native_id=safe_id(native, fallback=entity_type.value),
                          revision="dplan"),
            payload=payload, source=source, status="imported",
        )
        existing = seen.get(entity.id)
        if existing is not None:
            if existing.fingerprint != entity.fingerprint:
                duplicate_keys += 1
            return existing
        seen[entity.id] = entity
        entities.append(entity)
        return entity

    def member_of(entity: Entity, module_name: str, evidence: str) -> None:
        if not module_name:
            return
        relations.append(Relation(
            source=entity.id,
            target=EntityKey(project_id=project_id, entity_type=EntityType.MODULE.value,
                             native_id=safe_id(module_name), revision="dplan").id,
            kind=RelationKind.MEMBER_OF.value,
            status="confirmed", evidence=evidence, artifact_id=source,
        ))

    for row in plan.interfaces:
        add(EntityType.PORT, row.name, _payload(row))
    for row in plan.registers:
        add(EntityType.REGISTER, row.name or row.address, _payload(row))
    for row in plan.features:
        add(EntityType.FEATURE, row.feature_id or row.name, _payload(row))
    for row in plan.modules:
        add(EntityType.MODULE, row.name, _payload(row))

    contract = plan.model_contract
    model_module = contract.module or plan.design_name
    for row in contract.ports:
        port = add(EntityType.PORT, row.name, _payload(row))
        member_of(port, model_module, "model_contract.module")
    for row in contract.state:
        state = add(EntityType.MODEL_STATE, row.name, _payload(row))
        member_of(state, model_module, "model_contract.state")
        if row.parsed is False:
            issues.append(Issue(
                issue_id=f"issue:dplan_state_not_object:{project_id}:{safe_id(row.name)}",
                kind="dplan_state_not_object",
                message=f"model_contract.state 条目不是结构化对象：{row.raw[:120]}",
                severity=IssueSeverity.WARNING.value, refs=[source],
            ))
    for row in contract.behaviors:
        behavior = add(EntityType.BEHAVIOR, row.name, _payload(row))
        member_of(behavior, model_module, "model_contract.behaviors")

    report = validate(plan)
    for idx, item in enumerate(report.get("issues") or []):
        issues.append(Issue(
            issue_id=f"issue:dplan_{item.get('kind')}:{project_id}:{idx}",
            kind=f"dplan_{item.get('kind')}",
            message=str(item.get("message") or ""),
            severity=str(item.get("severity") or "warning"),
            blocking=bool(item.get("blocking")),
            refs=[source],
        ))
    if garbled:
        issues.append(Issue(
            issue_id=f"issue:dplan_garbled:{project_id}",
            kind="garbled_text",
            message=f"DPlan 文本含 {garbled} 个 U+FFFD；原样保留，不猜修",
            severity=IssueSeverity.WARNING.value, refs=[source],
        ))
    if duplicate_keys:
        issues.append(Issue(
            issue_id=f"issue:dplan_duplicate_keys:{project_id}",
            kind="duplicate_entity_key",
            message=f"DPlan 有 {duplicate_keys} 个相同 key 但内容不同的对象；保留首条，其余不覆盖",
            severity=IssueSeverity.INFO.value, refs=[source],
        ))

    return entities, relations, issues, {
        "version": plan.schema,
        "loader": "mental_ir_plane.dplan.DesignPlan",
        "counts": plan.counts(),
        "digest": plan.digest(),
    }


__all__ = ["import_dplan"]
