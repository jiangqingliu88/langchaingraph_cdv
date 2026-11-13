"""Unified Verification IR 的结构与引用闭合校验。"""
from __future__ import annotations

from typing import Any, Dict, List, Set

from .schema import RELATION_TYPES, SCHEMA, VerificationIR


def _attribute_ids(ir: VerificationIR) -> Set[str]:
    """属性域的身份：维度 key 与 coverpoint 名称（关系端点可以是它们）。"""
    ids: Set[str] = set()
    for dim in (ir.attributes.get("dimensions") or []):
        if not isinstance(dim, dict):
            continue
        if dim.get("key"):
            ids.add(str(dim["key"]))
        ids.update(str(cp) for cp in (dim.get("coverpoints") or []) if str(cp))
    return ids


def _constraint_ids(ir: VerificationIR) -> Set[str]:
    ids = {str(c) for c in (ir.verification.get("constraints") or []) if str(c)}
    for case in (ir.verification.get("cases") or []):
        if isinstance(case, dict):
            ids.update(str(c) for c in (case.get("constraints") or []) if str(c))
    return ids


def _ids_of(ir: VerificationIR) -> Set[str]:
    ids: Set[str] = _attribute_ids(ir) | _constraint_ids(ir)
    for case in (ir.verification.get("cases") or []):
        if isinstance(case, dict) and case.get("id"):
            ids.add(str(case["id"]))
    for tp in (ir.verification.get("testpoints") or []):
        if isinstance(tp, dict) and tp.get("tp_id"):
            ids.add(str(tp["tp_id"]))
    for group in (ir.attributes.get("groups") or []):
        if isinstance(group, dict) and group.get("group"):
            ids.add(str(group["group"]))
    for key in ("sva", "scb"):
        for item in (ir.verification.get(key) or []):
            if isinstance(item, dict) and item.get("id"):
                ids.add(str(item["id"]))
    for res in (ir.resources.get("resources") or []):
        if isinstance(res, dict) and res.get("resource_id"):
            ids.add(str(res["resource_id"]))
    for op in (ir.resources.get("operations") or []):
        if isinstance(op, dict) and op.get("operation_id"):
            ids.add(str(op["operation_id"]))
    return ids


def validate(ir: VerificationIR) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    if ir.schema != SCHEMA:
        errors.append({"rule": "unknown_schema", "target": ir.schema,
                       "message": f"期望 {SCHEMA}"})
    if not ir.identity.module_id:
        errors.append({"rule": "missing_module", "target": "identity",
                       "message": "identity.module_id 为空"})

    ids = _ids_of(ir)
    seen_relations: Set[str] = set()
    for relation in ir.relations:
        if relation.relation_type not in RELATION_TYPES:
            errors.append({"rule": "unknown_relation_type",
                           "target": relation.relation_id,
                           "message": f"未知关系类型 {relation.relation_type}"})
        if relation.relation_id in seen_relations:
            errors.append({"rule": "duplicate_relation",
                           "target": relation.relation_id,
                           "message": "relation_id 重复"})
        seen_relations.add(relation.relation_id)
        # 端点允许是域外身份（如 requirement id），但空串不允许
        if not relation.source_id or not relation.target_id:
            errors.append({"rule": "empty_relation_endpoint",
                           "target": relation.relation_id,
                           "message": "source_id / target_id 不能为空"})
        elif ids and (relation.source_id not in ids
                      or relation.target_id not in ids):
            warnings.append({"rule": "relation_endpoint_unknown",
                             "target": relation.relation_id,
                             "message": "端点不在当前 IR 的已知 id 集合里"})

    tp_ids = [str(tp.get("tp_id") or "")
              for tp in (ir.verification.get("testpoints") or [])
              if isinstance(tp, dict)]
    if len(tp_ids) != len(set(tp_ids)):
        errors.append({"rule": "duplicate_tp", "target": "testpoints",
                       "message": "同一 tp_id 出现多次 —— TP 身份必须稳定且唯一"})

    return {
        "schema": "verification_ir_validation_v1",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {"relations": len(ir.relations), "known_ids": len(ids),
                    "testpoints": len(tp_ids)},
    }


__all__ = ["validate"]
