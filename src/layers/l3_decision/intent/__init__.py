"""验证意图（Intent）—— 语义映射的候选假设与确认生命周期。"""
from .compiler import intents_from_case_ir
from .promote import IntentPromotionError, gate_check, promote
from .schema import (
    SCHEMA, Assumption, IntentGoal, IntentStatus, VerificationIntent,
    canonical_hash, from_dict,
)
from .store import load_intents, write_intents
from .validator import validate

__all__ = [
    "SCHEMA", "Assumption", "IntentGoal", "IntentPromotionError", "IntentStatus",
    "VerificationIntent", "canonical_hash", "from_dict", "gate_check",
    "intents_from_case_ir", "load_intents", "promote", "validate",
    "write_intents",
]
