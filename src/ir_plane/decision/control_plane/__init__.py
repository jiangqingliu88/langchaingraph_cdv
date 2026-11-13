"""Control Plane —— 动作级治理：AUTO / APPROVAL / FORBIDDEN + 审计。"""
from .actions import APPROVAL, AUTO, DEFAULT_ACTIONS, FORBIDDEN
from .approvals import approval, approval_token
from .decide import ACTIONS_FILE, decide, decide_and_record, record
from .policy import load_policy
from .roles import ROLE_ACTIONS, allowed, allowed_actions, is_forbidden

__all__ = [
    "ACTIONS_FILE", "APPROVAL", "AUTO", "DEFAULT_ACTIONS", "FORBIDDEN",
    "ROLE_ACTIONS", "allowed", "allowed_actions", "approval", "approval_token",
    "decide", "decide_and_record", "is_forbidden", "load_policy", "record",
]
