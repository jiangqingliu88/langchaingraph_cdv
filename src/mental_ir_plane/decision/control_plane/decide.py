"""`decide(action, context)` —— AUTO / APPROVAL / FORBIDDEN，并写动作审计。

判定顺序：
  1. 禁止类动作 → FORBIDDEN（角色不能豁免）；
  2. 角色白名单（工具调用除外，它由执行器统一发起）；
  3. 策略表（工具动作走 `tool_action` 默认值，未知动作默认拒绝）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from .actions import APPROVAL, AUTO, FORBIDDEN
from .policy import load_policy
from .roles import allowed, is_forbidden

ACTIONS_FILE = Path("docs") / "action_audit.jsonl"


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def decide(action: str, *, role: str = "", module: str = "",
           policy: Dict[str, Any] = None, input_sha: str = "") -> Dict[str, Any]:
    action = str(action or "")
    policy = policy or load_policy(module)
    defaults = policy.get("defaults") or {}
    entry = (policy.get("rules") or {}).get(action)
    if is_forbidden(action):
        decision, risk, policy_id = FORBIDDEN, "CRITICAL", "CP-FORBIDDEN"
    elif entry and entry.get("enabled") is not False:
        decision = str(entry.get("decision") or AUTO).upper()
        risk = str(entry.get("risk") or "MEDIUM").upper()
        policy_id = f"CP-{action}"
    elif action.startswith("tool:"):
        decision = str(defaults.get("tool_action") or AUTO).upper()
        risk = str(defaults.get("tool_risk") or "MEDIUM").upper()
        policy_id = "CP-TOOL"
    else:
        decision = str(defaults.get("unknown_action") or FORBIDDEN).upper()
        risk, policy_id = "HIGH", "CP-UNKNOWN"
    reason = ""
    if decision != FORBIDDEN and role and not action.startswith("tool:") \
            and not allowed(role, action):
        decision, reason = FORBIDDEN, f"角色 {role} 无权执行 {action}"
        policy_id = "CP-ROLE"
    return {"schema": "control_decision_v1", "action": action, "role": role,
            "decision": decision, "risk": risk, "policy_id": policy_id,
            "reason": reason, "input_sha": input_sha or ""}


def record(root: str | Path, decision: Dict[str, Any], *,
           actor: str = "", output_sha: str = "", appr_id: str = "",
           metadata: Dict[str, Any] = None) -> Dict[str, Any]:
    """把决策写进 `docs/action_audit.jsonl`（只追加）。"""
    body = {
        "schema": "action_audit_v1",
        "action": decision.get("action", ""),
        "role": decision.get("role", ""),
        "decision": decision.get("decision", ""),
        "risk": decision.get("risk", ""),
        "policy_id": decision.get("policy_id", ""),
        "reason": decision.get("reason", ""),
        "actor": str(actor or ""),
        # 人工审批 token：绑定被批动作的输入哈希（见 approvals.py）。
        "appr_id": str(appr_id or ""),
        "input_sha256": decision.get("input_sha", ""),
        "output_sha256": str(output_sha or ""),
        "metadata": dict(metadata or {}),
    }
    body["act_id"] = f"ACT-{_sha(json.dumps(body, ensure_ascii=False, sort_keys=True))[:12]}"
    path = Path(root) / ACTIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(body, ensure_ascii=False) + "\n")
    return body


def decide_and_record(root: str | Path, action: str, *, actor: str = "",
                      role: str = "", module: str = "",
                      input_sha: str = "", output_sha: str = "",
                      metadata: Dict[str, Any] = None) -> Dict[str, Any]:
    decision = decide(action, role=role, module=module, input_sha=input_sha)
    record(root, decision, actor=actor, output_sha=output_sha,
           metadata=metadata)
    return decision


__all__ = ["ACTIONS_FILE", "decide", "decide_and_record", "record"]
