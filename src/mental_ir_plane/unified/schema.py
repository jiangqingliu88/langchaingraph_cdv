"""统一 IR 的根包络与对象图类型（`unified_design_verification_ir_v1`）。

分层原则：

    envelope     项目身份 + 原始 artifact / profiles + build metadata
    entities     规范化对象（module/port/feature/goal/requirement/testpoint…）
    relations    有类型的边（references / aligns_with / conflicts_with / …）
    issues       缺输入、冲突、乱码、待定后端
    views         Mental / DPlan / VPlan 三种投影，不互相覆盖

**这不是签核表**：`status=candidate` 的边和实体只是候选关联；Execution 与
Evidence 仍由独立记录回答。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


SCHEMA = "unified_design_verification_ir_v1"


class Mode(str, Enum):
    IMPORT_ONLY = "import_only"
    LOGICAL_PROJECTION = "logical_projection"
    REVIEWED_PROJECTION = "reviewed_projection"


class EntityType(str, Enum):
    MODULE = "module"
    PORT = "port"
    REGISTER = "register"
    PARAMETER = "parameter"
    FEATURE = "feature"
    BEHAVIOR = "behavior"
    MODEL_STATE = "model_state"
    GOAL = "goal"
    ASSUMPTION = "assumption"
    AMBIGUITY = "ambiguity"
    VERIFICATION_INTENT = "verification_intent"
    RISK = "risk"
    REQUIREMENT = "requirement"
    CONTRACT = "contract"
    TESTPOINT = "testpoint"
    CASE = "case"
    ARTIFACT = "artifact"
    ISSUE = "issue"


class RelationKind(str, Enum):
    REFERENCES = "references"
    ALIGNS_WITH = "aligns_with"
    CONFLICTS_WITH = "conflicts_with"
    CONFIRMED_BY = "confirmed_by"
    EVIDENCED_BY = "evidenced_by"
    SUPERSEDES = "supersedes"
    MEMBER_OF = "member_of"


class RelationStatus(str, Enum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProjectRef:
    project_id: str
    top_module: str = ""
    design_name: str = ""
    revision: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactRef:
    artifact_id: str
    kind: str
    path: str = ""
    sha256: str = ""
    status: str = "present"
    counts: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Profile:
    kind: str
    version: str = ""
    loader: str = ""
    content_hash: str = ""
    status: str = "imported"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EntityKey:
    project_id: str
    entity_type: str
    native_id: str
    revision: str = ""

    @property
    def id(self) -> str:
        base = f"{self.project_id}:{self.entity_type}:{self.native_id}"
        return f"{base}@{self.revision}" if self.revision else base


@dataclass
class Entity:
    key: EntityKey
    payload: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    status: str = "imported"
    aliases: List[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.key.id

    @property
    def entity_type(self) -> str:
        return self.key.entity_type

    @property
    def fingerprint(self) -> str:
        return sha256_value({"type": self.entity_type, "payload": self.payload})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "key": asdict(self.key),
            "payload": self.payload,
            "source": self.source,
            "status": self.status,
            "aliases": list(self.aliases),
            "fingerprint": self.fingerprint,
        }


@dataclass
class Relation:
    source: str
    target: str
    kind: str
    status: str = RelationStatus.CANDIDATE.value
    score: float = 0.0
    evidence: str = ""
    artifact_id: str = ""

    @property
    def id(self) -> str:
        return f"rel:{self.kind}:{self.source}->{self.target}"

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "id": self.id}


@dataclass
class Issue:
    issue_id: str
    kind: str
    message: str
    severity: str = IssueSeverity.WARNING.value
    blocking: bool = False
    refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UnifiedIR:
    project: ProjectRef
    mode: str = Mode.LOGICAL_PROJECTION.value
    artifacts: List[ArtifactRef] = field(default_factory=list)
    profiles: List[Profile] = field(default_factory=list)
    entities: List[Entity] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    execution_refs: List[Dict[str, Any]] = field(default_factory=list)
    build_metadata: Dict[str, Any] = field(default_factory=dict)
    schema: str = SCHEMA

    # ── 构造 ──────────────────────────────────────────────

    def add_entity(self, entity: Entity) -> Entity:
        existing = self.entity(entity.id)
        if existing is not None:
            if existing.fingerprint == entity.fingerprint:
                return existing
            issue = Issue(
                issue_id=f"issue:duplicate:{entity.id}",
                kind="duplicate_entity_key",
                message=f"{entity.id} 出现相同 key 但不同内容；保留两条来源，不覆盖",
                refs=[entity.source],
            )
            if not any(i.issue_id == issue.issue_id for i in self.issues):
                self.issues.append(issue)
            return existing
        self.entities.append(entity)
        return entity

    def add_relation(self, relation: Relation) -> Relation:
        if any(r.id == relation.id for r in self.relations):
            return next(r for r in self.relations if r.id == relation.id)
        self.relations.append(relation)
        return relation

    def add_issue(self, issue: Issue) -> Issue:
        if not any(i.issue_id == issue.issue_id for i in self.issues):
            self.issues.append(issue)
        return issue

    def entity(self, entity_id: str) -> Optional[Entity]:
        return next((e for e in self.entities if e.id == entity_id), None)

    def by_type(self, entity_type: str) -> List[Entity]:
        return [e for e in self.entities if e.entity_type == entity_type]

    # ── 稳定哈希 ──────────────────────────────────────────

    def semantic_payload(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "mode": self.mode,
            "project": self.project.to_dict(),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "profiles": [p.to_dict() for p in self.profiles],
            "entities": sorted((e.to_dict() for e in self.entities), key=lambda x: x["id"]),
            "relations": sorted((r.to_dict() for r in self.relations), key=lambda x: x["id"]),
            "issues": sorted((i.to_dict() for i in self.issues), key=lambda x: x["issue_id"]),
            "execution_refs": self.execution_refs,
        }

    def semantic_digest(self) -> str:
        return sha256_value(self.semantic_payload())

    # ── 序列化 ────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.semantic_payload(),
            "semantic_digest": self.semantic_digest(),
            "build_metadata": dict(self.build_metadata),
        }

    @classmethod
    def from_dict(cls, doc: Dict[str, Any]) -> "UnifiedIR":
        project = doc.get("project") or {}
        ir = cls(
            project=ProjectRef(
                project_id=str(project.get("project_id") or ""),
                top_module=str(project.get("top_module") or ""),
                design_name=str(project.get("design_name") or ""),
                revision=str(project.get("revision") or ""),
            ),
            mode=str(doc.get("mode") or Mode.IMPORT_ONLY.value),
            schema=str(doc.get("schema") or SCHEMA),
            build_metadata=dict(doc.get("build_metadata") or {}),
            execution_refs=list(doc.get("execution_refs") or []),
        )
        for row in doc.get("artifacts") or []:
            ir.artifacts.append(ArtifactRef(**row))
        for row in doc.get("profiles") or []:
            ir.profiles.append(Profile(**row))
        for row in doc.get("entities") or []:
            key = row.get("key") or {}
            ir.entities.append(Entity(
                key=EntityKey(
                    project_id=str(key.get("project_id") or ir.project.project_id),
                    entity_type=str(key.get("entity_type") or ""),
                    native_id=str(key.get("native_id") or ""),
                    revision=str(key.get("revision") or ""),
                ),
                payload=dict(row.get("payload") or {}),
                source=str(row.get("source") or ""),
                status=str(row.get("status") or "imported"),
                aliases=list(row.get("aliases") or []),
            ))
        for row in doc.get("relations") or []:
            ir.relations.append(Relation(
                source=str(row.get("source") or ""),
                target=str(row.get("target") or ""),
                kind=str(row.get("kind") or ""),
                status=str(row.get("status") or RelationStatus.CANDIDATE.value),
                score=float(row.get("score") or 0.0),
                evidence=str(row.get("evidence") or ""),
                artifact_id=str(row.get("artifact_id") or ""),
            ))
        for row in doc.get("issues") or []:
            ir.issues.append(Issue(
                issue_id=str(row.get("issue_id") or ""),
                kind=str(row.get("kind") or ""),
                message=str(row.get("message") or ""),
                severity=str(row.get("severity") or IssueSeverity.WARNING.value),
                blocking=bool(row.get("blocking")),
                refs=list(row.get("refs") or []),
            ))
        return ir

    def summary(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for entity in self.entities:
            counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
        return {
            "schema": self.schema,
            "mode": self.mode,
            "project": self.project.to_dict(),
            "entities": counts,
            "relations": len(self.relations),
            "candidate_relations": sum(
                1 for r in self.relations if r.status == RelationStatus.CANDIDATE.value),
            "blocking_issues": sum(1 for i in self.issues if i.blocking),
            "issues": len(self.issues),
            "semantic_digest": self.semantic_digest(),
        }


__all__ = [
    "SCHEMA",
    "Mode",
    "EntityType",
    "RelationKind",
    "RelationStatus",
    "IssueSeverity",
    "ProjectRef",
    "ArtifactRef",
    "Profile",
    "EntityKey",
    "Entity",
    "Relation",
    "Issue",
    "UnifiedIR",
    "sha256_value",
]
