"""Resource / Interaction Model —— 地址、资源、并发与冲突策略。"""
from .address import AddressRange, overlap, overlaps
from .model import ResourceModel, from_dict
from .policy import evaluate
from .scenario import compile_scenarios, coverage_summary
from .schema import (
    OVERLAP_KINDS, RELATIONS, Resource, ResourceAccess, ResourceInteraction,
    ResourceOperation,
)

__all__ = [
    "OVERLAP_KINDS", "RELATIONS", "AddressRange", "Resource",
    "ResourceAccess", "ResourceInteraction", "ResourceModel",
    "ResourceOperation", "compile_scenarios", "coverage_summary", "evaluate",
    "from_dict", "overlap", "overlaps",
]
