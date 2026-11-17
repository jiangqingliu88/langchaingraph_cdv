"""审批 token —— 绑定被批动作的内容哈希，不能挪用到另一份输入上。"""
from __future__ import annotations

import hashlib
from typing import Any, Dict


def approval_token(action: str, *, actor: str = "", input_sha: str = "") -> str:
    body = f"{action}|{actor}|{input_sha}"
    return f"APR-{hashlib.sha256(body.encode('utf-8')).hexdigest()[:12]}"


def approval(
    action: str, *, approved_by: str, input_sha: str,
    reason: str = "", data: Dict[str, Any] = None
) -> Dict[str, Any]:
    if not approved_by:
        raise ValueError("审批必须有 approved_by")
    return {
        "schema": "approval_v1",
        "action": action,
        "approved_by": approved_by,
        "token": approval_token(action, actor=approved_by, input_sha=input_sha),
        "input_sha256": input_sha,
        "reason": reason,
        "fact_class": "HUMAN_DECISION",
        "producer_class": "human",
        "data": dict(data or {}),
    }


__all__ = ["approval", "approval_token"]
