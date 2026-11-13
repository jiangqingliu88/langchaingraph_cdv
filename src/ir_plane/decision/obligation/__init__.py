"""统一验证义务 —— 模型、推导、动作映射。"""
from .actions import actions_for, candidates
from .derive import derive_obligations, map_status, summary
from .model import (
    DONE, TERMINAL, ObligationStatus, VerificationObligation,
    from_contract_obligation,
)

__all__ = [
    "DONE", "TERMINAL", "ObligationStatus", "VerificationObligation",
    "actions_for", "candidates", "derive_obligations",
    "from_contract_obligation", "map_status", "summary",
]
