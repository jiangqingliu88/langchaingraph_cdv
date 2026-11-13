"""Specification/IR 契约：正式需求、推导、假设、未知与冲突的同一语义源。

本包只定义语义和来源，不调用 LLM、解析 RTL、执行 EDA 或批准签核。
Agent/Generation 可以产生候选；CONFIRMED 需要规范来源或明确人工依据。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

SCHEMA = "specification_contract_v1"
READINESS_SCHEMA = "verification_readiness_v1"


class SpecStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    DERIVED = "DERIVED"
    ASSUMED = "ASSUMED"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class LifecycleStage(str, Enum):
    INGESTION = "ingestion"
    EXTRACTION = "extraction"
    RECONCILIATION = "reconciliation"
    GAP_ANALYSIS = "gap_analysis"
    CLARIFICATION = "clarification"
    SYNTHESIS = "synthesis"
    IR_COMPILATION = "ir_compilation"
    VALIDATION = "validation"
    EVOLUTION = "evolution"


LIFECYCLE = tuple(stage.value for stage in LifecycleStage)


class SpecSchemaError(ValueError):
    """契约结构错误。它不能被解释为一份已完成验证的规格。"""


@dataclass
class SpecSource:
    source_id: str
    kind: str
    locator: str
    sha256: str = ""
    producer: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SpecRequirement:
    requirement_id: str
    field: str
    value: Any = None
    statement: str = ""
    status: str = SpecStatus.UNKNOWN.value
    source_ids: list[str] = field(default_factory=list)
    intent_ids: list[str] = field(default_factory=list)
    confirmed_by: str = ""
    rationale: str = ""
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_verification_intent(self):
        """复用已有 Intent 的 CANDIDATE/CONFIRMED，不复制意图语义。"""
        from src.ir_plane.decision.intent.schema import from_dict

        confirmed = self.status == SpecStatus.CONFIRMED.value
        return from_dict(
            {
                "case_id": self.field,
                "statement": self.statement or self.field,
                "module": self.requirement_id,
                "source": "specification",
                "source_span": ",".join(self.source_ids),
                "status": "CONFIRMED" if confirmed else "CANDIDATE",
                "confirmed_by": self.confirmed_by if confirmed else "",
                "intent_id": self.intent_ids[0] if self.intent_ids else "",
                "goals": [{"kind": "checker", "target": self.field, "rationale": self.rationale}],
            }
        ).seal()


@dataclass
class GapRecord:
    field: str
    reason: str
    status: str = "OPEN"
    source_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConflictRecord:
    field: str
    description: str
    values: dict[str, Any] = field(default_factory=dict)
    status: str = "OPEN"
    source_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LifecycleEvent:
    stage: str
    detail: str = ""
    status: str = "VISITED"
    iteration: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _items(value: Any, name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SpecSchemaError(f"{name} 必须是列表")
    if any(not isinstance(row, dict) for row in value):
        raise SpecSchemaError(f"{name} 的每一项必须是对象")
    return value


def _gaps(value: Any) -> list[GapRecord]:
    if isinstance(value, dict):
        return [GapRecord(field=str(name), reason=str(reason)) for name, reason in value.items()]
    return [
        GapRecord(
            field=str(row.get("field") or ""),
            reason=str(row.get("reason") or ""),
            status=str(row.get("status") or "OPEN").upper(),
            source_ids=list(row.get("source_ids") or []),
        )
        for row in _items(value, "gaps")
    ]


def _requirement(row: dict[str, Any]) -> SpecRequirement:
    return SpecRequirement(
        requirement_id=str(row.get("requirement_id") or row.get("id") or ""),
        field=str(row.get("field") or row.get("name") or ""),
        value=row.get("value"),
        statement=str(row.get("statement") or row.get("text") or ""),
        status=str(row.get("status") or SpecStatus.UNKNOWN.value).upper(),
        source_ids=[str(x) for x in (row.get("source_ids") or [])],
        intent_ids=[str(x) for x in (row.get("intent_ids") or [])],
        confirmed_by=str(row.get("confirmed_by") or ""),
        rationale=str(row.get("rationale") or ""),
        properties=dict(row.get("properties") or {}),
    )


def _source(row: dict[str, Any]) -> SpecSource:
    return SpecSource(
        source_id=str(row.get("source_id") or row.get("id") or ""),
        kind=str(row.get("kind") or "spec"),
        locator=str(row.get("locator") or row.get("uri") or ""),
        sha256=str(row.get("sha256") or ""),
        producer=str(row.get("producer") or ""),
        metadata=dict(row.get("metadata") or {}),
    )


def _conflict(row: dict[str, Any]) -> ConflictRecord:
    return ConflictRecord(
        field=str(row.get("field") or ""),
        description=str(row.get("description") or row.get("reason") or ""),
        values=dict(row.get("values") or {}),
        status=str(row.get("status") or "OPEN").upper(),
        source_ids=list(row.get("source_ids") or []),
    )


def _lifecycle(row: dict[str, Any]) -> LifecycleEvent:
    return LifecycleEvent(
        stage=str(row.get("stage") or ""), detail=str(row.get("detail") or ""),
        status=str(row.get("status") or "VISITED"), iteration=int(row.get("iteration") or 1),
    )


@dataclass
class SpecificationContract:
    document_id: str
    domain: str = "generic"
    version: int = 1
    sources: list[SpecSource] = field(default_factory=list)
    requirements: list[SpecRequirement] = field(default_factory=list)
    gaps: list[GapRecord] = field(default_factory=list)
    conflicts: list[ConflictRecord] = field(default_factory=list)
    lifecycle: list[LifecycleEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> "SpecificationContract":
        if not isinstance(doc, dict):
            raise SpecSchemaError("Specification 根节点必须是对象")
        for key in ("sources", "requirements", "conflicts", "lifecycle"):
            _items(doc.get(key), key)
        return cls(
            document_id=str(doc.get("document_id") or doc.get("module") or ""),
            domain=str(doc.get("domain") or "generic"),
            version=int(doc.get("version") or 1),
            sources=[_source(r) for r in (doc.get("sources") or [])],
            requirements=[_requirement(r) for r in (doc.get("requirements") or [])],
            gaps=_gaps(doc.get("gaps")),
            conflicts=[_conflict(r) for r in (doc.get("conflicts") or [])],
            lifecycle=[_lifecycle(r) for r in (doc.get("lifecycle") or [])],
            metadata=dict(doc.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "document_id": self.document_id,
            "domain": self.domain,
            "version": self.version,
            "sources": [r.to_dict() for r in self.sources],
            "requirements": [r.to_dict() for r in self.requirements],
            "gaps": [r.to_dict() for r in self.gaps],
            "conflicts": [r.to_dict() for r in self.conflicts],
            "lifecycle": [r.to_dict() for r in self.lifecycle],
            "metadata": self.metadata,
        }

    def content_hash(self) -> str:
        text = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return "SPC-" + hashlib.sha256(text.encode()).hexdigest()[:24]

    def traceability(self) -> list[dict[str, str]]:
        edges = [
            {"from": sid, "to": req.requirement_id, "relation": "supports"}
            for req in self.requirements
            for sid in req.source_ids
        ]
        edges += [
            {"from": req.requirement_id, "to": iid, "relation": "refines"}
            for req in self.requirements
            for iid in req.intent_ids
        ]
        return edges

    def advance(self, stage: LifecycleStage | str, detail: str = "", status: str = "VISITED") -> None:
        """有序记录生命周期；同一阶段可重入，并保留每轮而非覆盖历史。"""
        stage = stage.value if isinstance(stage, LifecycleStage) else str(stage)
        if stage not in LIFECYCLE:
            raise SpecSchemaError(f"未知生命周期阶段：{stage}")
        seen = [event.stage for event in self.lifecycle]
        if seen and LIFECYCLE.index(stage) > LIFECYCLE.index(seen[-1]) + 1:
            raise SpecSchemaError(f"生命周期不能从 {seen[-1]} 跳到 {stage}")
        iteration = 1 + sum(event.stage == stage for event in self.lifecycle)
        self.lifecycle.append(LifecycleEvent(stage, detail, status, iteration))


def contract_from(value: SpecificationContract | dict[str, Any]) -> SpecificationContract:
    return value if isinstance(value, SpecificationContract) else SpecificationContract.from_dict(value)


__all__ = [
    "ConflictRecord",
    "GapRecord",
    "LIFECYCLE",
    "LifecycleEvent",
    "LifecycleStage",
    "READINESS_SCHEMA",
    "SCHEMA",
    "SpecRequirement",
    "SpecSchemaError",
    "SpecSource",
    "SpecStatus",
    "SpecificationContract",
    "contract_from",
]
