"""统一 IR 构建器 —— 一个项目作用域，三种投影，候选关系不升级为证据。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from .adapters import import_dplan, import_mental, import_vplan
from .normalize import score, text_of, tokens
from .schema import (
    ArtifactRef,
    Entity,
    EntityType,
    Issue,
    IssueSeverity,
    Mode,
    Profile,
    ProjectRef,
    Relation,
    RelationKind,
    UnifiedIR,
    sha256_value,
)

_MATCH_THRESHOLD = 0.35


def _sha256_file(path: str) -> str:
    try:
        h = hashlib.sha256()
        with Path(path).open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _artifact(kind: str, path: str, data: Any) -> ArtifactRef:
    content_hash = _sha256_file(path) if path else sha256_value(data)
    return ArtifactRef(artifact_id=f"artifact:{kind}", kind=kind, path=str(path),
                       sha256=content_hash, status="present" if path and Path(path).is_file() else "imported")


def _entity_id(project_id: str, entity_type: str, native_id: str) -> str:
    from .schema import EntityKey

    return EntityKey(project_id=project_id, entity_type=entity_type,
                     native_id=str(native_id)).id


def _row_text(entity: Entity) -> str:
    payload = entity.payload
    return text_of(payload, (
        "name", "description", "statement", "question", "test_point",
        "stimulus", "expected", "feature_l1", "feature_l2", "feature_l3",
        "req_id", "feature_id", "tp_id",
    ))


def _link(ir: UnifiedIR, source: Entity, targets: Iterable[Entity], *,
          threshold: float = _MATCH_THRESHOLD, evidence: str) -> None:
    """只保留**最佳候选**，不把 O(n²) 的弱匹配全部铺进对象图。"""
    source_tokens = tokens(_row_text(source))
    if not source_tokens:
        return
    best: Optional[Entity] = None
    best_score = 0.0
    for target in targets:
        value = score(source_tokens, tokens(_row_text(target)))
        if value > best_score:
            best, best_score = target, value
    if best is not None and best_score >= threshold:
        ir.add_relation(Relation(
            source=source.id, target=best.id,
            kind=RelationKind.ALIGNS_WITH.value,
            status="candidate", score=best_score, evidence=evidence,
        ))


def build_unified_ir(*, project_id: str = "", top_module: str = "",
                     mental: Any = None, dplan: Optional[Dict[str, Any]] = None,
                     vplan: Any = None,
                     artifacts: Sequence[Tuple[str, str, Any]] = (),
                     mode: str = Mode.LOGICAL_PROJECTION.value) -> UnifiedIR:
    """构建统一 IR；缺哪类输入就跳过哪类投影，不补造对象。"""
    mental_module = ""
    if mental is not None:
        mental_module = str(getattr(mental, "module", "") or
                            (mental.get("module") if isinstance(mental, dict) else ""))
    def _field(obj: Any, name: str) -> str:
        if isinstance(obj, dict):
            return str(obj.get(name) or "")
        return str(getattr(obj, name, "") or "")

    design_name = _field(dplan, "design_name") if dplan is not None else ""
    vplan_module = _field(vplan, "module") if vplan is not None else ""
    pid = str(project_id or design_name or mental_module or vplan_module or "project")
    project = ProjectRef(
        project_id=pid,
        top_module=str(top_module or mental_module or design_name or vplan_module),
        design_name=design_name,
    )
    ir = UnifiedIR(project=project, mode=mode)

    # 原始 artifacts / profiles
    inputs = {
        "mental": (mental, "mental_ir_plane.model.MentalIR"),
        "dplan": (dplan, "dplan_json"),
        "vplan": (vplan, "vplan_snapshot"),
    }
    for kind, path, data in artifacts:
        ir.artifacts.append(_artifact(kind, str(path), data))
    for kind, (data, loader) in inputs.items():
        if data is None:
            ir.add_issue(Issue(
                issue_id=f"issue:missing_input:{pid}:{kind}",
                kind="missing_input",
                message=f"缺少 {kind} 输入；对应投影为空",
                severity=IssueSeverity.INFO.value,
            ))
            continue
        artifact = next((a for a in ir.artifacts if a.kind == kind), None)
        artifact_id = artifact.artifact_id if artifact else f"artifact:{kind}"
        try:
            if kind == "mental":
                entities, relations, issues, meta = import_mental(data, project_id=pid, artifact_id=artifact_id)
            elif kind == "dplan":
                entities, relations, issues, meta = import_dplan(data, project_id=pid, artifact_id=artifact_id)
            else:
                entities, relations, issues, meta = import_vplan(data, project_id=pid, artifact_id=artifact_id)
        except Exception as exc:  # noqa: BLE001 输入不合法 → 记录缺口，不中断其余投影
            ir.add_issue(Issue(
                issue_id=f"issue:import_failed:{pid}:{kind}",
                kind="import_failed",
                message=f"{kind} 导入失败：{type(exc).__name__}: {exc}",
                severity=IssueSeverity.ERROR.value,
                blocking=True,
                refs=[artifact_id],
            ))
            continue
        for entity in entities:
            ir.add_entity(entity)
        for relation in relations:
            ir.add_relation(relation)
        for issue in issues:
            ir.add_issue(issue)
        ir.profiles.append(Profile(
            kind=kind,
            version=str(meta.get("version") or ""),
            loader=str(meta.get("loader") or loader),
            content_hash=(artifact.sha256 if artifact else ""),
        ))
        if artifact is not None:
            artifact.counts = dict(meta.get("counts") or {})

    # 跨投影候选关系（只在同 project_id 内）
    dplan_features = ir.by_type(EntityType.FEATURE.value)
    # 用来源区分 DPlan / VPlan feature
    vplan_features = [e for e in dplan_features if e.source.startswith("artifact:vplan")]
    dplan_only = [e for e in dplan_features if not e.source.startswith("artifact:vplan")]
    for entity in dplan_only:
        _link(ir, entity, vplan_features, evidence="dplan_feature↔vplan_feature token match")
    for entity in vplan_features:
        _link(ir, entity, dplan_only, evidence="vplan_feature↔dplan_feature token match")
    # 同名 native id 是强候选（但仍不升级为 confirmed：内容/修订未核验）
    by_native = {e.key.native_id: e for e in vplan_features}
    for entity in dplan_only:
        twin = by_native.get(entity.key.native_id)
        if twin is not None:
            ir.add_relation(Relation(
                source=entity.id, target=twin.id,
                kind=RelationKind.ALIGNS_WITH.value,
                status="candidate", score=1.0,
                evidence="same_native_feature_id; content/revision not verified",
            ))

    intents = ir.by_type(EntityType.VERIFICATION_INTENT.value)
    tps = ir.by_type(EntityType.TESTPOINT.value)
    for intent in intents:
        _link(ir, intent, tps, evidence="mental_intent↔vplan_testpoint token match")
    goals = ir.by_type(EntityType.GOAL.value)
    reqs = ir.by_type(EntityType.REQUIREMENT.value)
    for goal in goals:
        _link(ir, goal, reqs, evidence="mental_goal↔vplan_requirement token match")

    ir.build_metadata = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "mental_ir_plane.unified.build",
        "mode": mode,
        "match_threshold": _MATCH_THRESHOLD,
        "modules_mapped": "NOT_COMPUTED",
        "input_counts": {
            "mental_entities": sum(1 for e in ir.entities if e.source == "artifact:mental"),
            "dplan_entities": sum(1 for e in ir.entities if e.source == "artifact:dplan"),
            "vplan_entities": sum(1 for e in ir.entities if e.source == "artifact:vplan"),
        },
    }
    return ir


__all__ = ["build_unified_ir"]
