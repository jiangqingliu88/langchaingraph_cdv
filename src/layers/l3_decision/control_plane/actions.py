"""动作词表与风险分类 —— 默认拒绝，白名单放行。"""
from __future__ import annotations

AUTO, APPROVAL, FORBIDDEN = "AUTO", "APPROVAL", "FORBIDDEN"

#: 动作 → (决策, 风险)。这些是**默认值**，YAML 可覆盖。
DEFAULT_ACTIONS = {
    # ── 只读 / 生成候选：可自动 ──
    "read_evidence": (AUTO, "LOW"),
    "read_coverage": (AUTO, "LOW"),
    "run_simulation": (AUTO, "MEDIUM"),
    "run_regression": (AUTO, "MEDIUM"),
    "run_formal": (AUTO, "MEDIUM"),
    "run_emulation": (AUTO, "MEDIUM"),
    "generate_intent_candidate": (AUTO, "LOW"),
    "generate_assertion": (AUTO, "LOW"),
    "generate_constraint": (AUTO, "LOW"),
    "generate_test": (AUTO, "LOW"),
    "generate_debug_hypothesis": (AUTO, "LOW"),
    "generate_interpretation": (AUTO, "LOW"),
    # ── 改语义 / 改边界：必须审批 ──
    "modify_intent": (APPROVAL, "HIGH"),
    "confirm_intent": (APPROVAL, "HIGH"),
    "change_assumption": (APPROVAL, "HIGH"),
    "promote_hypothesis_to_fact": (APPROVAL, "HIGH"),
    "waive_failing_proof": (APPROVAL, "HIGH"),
    "waive_obligation": (APPROVAL, "HIGH"),
    "accept_caveat": (APPROVAL, "HIGH"),
    "affect_signoff_state": (APPROVAL, "HIGH"),
    "disable_gate_rule": (APPROVAL, "HIGH"),
    "change_risk_class": (APPROVAL, "HIGH"),
    # ── 破坏证据链：禁止 ──
    "edit_ledger": (FORBIDDEN, "CRITICAL"),
    "fabricate_evidence": (FORBIDDEN, "CRITICAL"),
    "bypass_gate": (FORBIDDEN, "CRITICAL"),
    "downgrade_verdict_silently": (FORBIDDEN, "CRITICAL"),
    "write_contract_from_unconfirmed_intent": (FORBIDDEN, "CRITICAL"),
}

#: 工具调用的默认策略（工具名不在词表里时用）。
TOOL_ACTION_DECISION = (AUTO, "MEDIUM")

__all__ = ["APPROVAL", "AUTO", "DEFAULT_ACTIONS", "FORBIDDEN",
           "TOOL_ACTION_DECISION"]
