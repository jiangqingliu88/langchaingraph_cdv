"""Unified Verification IR v3 —— 五域统一验证语义。"""
from .compiler import compile_from_case_ir
from .schema import (
    IR_VERSION, RELATION_TYPES, SCHEMA, IRIdentity, IRRelation,
    VerificationIR, canonical_hash,
)
from .validator import validate

__all__ = [
    "IR_VERSION", "RELATION_TYPES", "SCHEMA", "IRIdentity", "IRRelation",
    "VerificationIR", "canonical_hash", "compile_from_case_ir", "validate",
]
