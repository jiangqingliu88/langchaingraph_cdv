"""Exact Coverage Attribution —— Bin 身份、sidecar、EXACT/WEAK/UNKNOWN。"""
from .bin_identity import bin_identity, hit_fact
from .classify import (
    LEVELS, classify_record, from_attribution_doc, quality_gate, rates,
)
from .report import build_attribution_v2, write_attribution_v2
from .sidecar import SCHEMA, build_sidecar, validate_sidecar

__all__ = [
    "LEVELS", "SCHEMA", "bin_identity", "build_attribution_v2",
    "build_sidecar", "classify_record", "from_attribution_doc", "hit_fact",
    "quality_gate", "rates", "validate_sidecar", "write_attribution_v2",
]
