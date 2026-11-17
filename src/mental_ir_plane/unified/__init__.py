"""统一设计验证 IR —— Mental 为唯一 IR 根，DPlan/VPlan 是投影输入。

分层：`schema`（包络/实体/关系/缺口）→ `adapters`（三类输入）→ `build`
（候选关系与缺口）→ `views`（三投影）→ `store`（原子读写）。
"""
from .adapters import import_dplan, import_mental, import_vplan
from .build import build_unified_ir
from .schema import (
    SCHEMA,
    ArtifactRef,
    Entity,
    EntityKey,
    EntityType,
    Issue,
    IssueSeverity,
    Mode,
    Profile,
    ProjectRef,
    Relation,
    RelationKind,
    RelationStatus,
    UnifiedIR,
)
from .store import read_unified, write_unified
from .views import dplan_view, mental_view, views, vplan_view

__all__ = [
    "SCHEMA", "Mode", "EntityType", "RelationKind", "RelationStatus",
    "IssueSeverity", "ProjectRef", "ArtifactRef", "Profile", "EntityKey",
    "Entity", "Relation", "Issue", "UnifiedIR",
    "build_unified_ir", "import_mental", "import_dplan", "import_vplan",
    "mental_view", "dplan_view", "vplan_view", "views",
    "read_unified", "write_unified",
]
