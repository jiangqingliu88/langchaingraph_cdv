"""Specification Contract 属于既有 IR Plane，不是新的顶层 Plane。"""

from .contracts import (
    LIFECYCLE,
    READINESS_SCHEMA,
    SCHEMA,
    ConflictRecord,
    GapRecord,
    LifecycleEvent,
    LifecycleStage,
    SpecificationContract,
    SpecRequirement,
    SpecSchemaError,
    SpecSource,
    SpecStatus,
    contract_from,
)

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
