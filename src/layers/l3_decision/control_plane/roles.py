"""受治理智能体团队的角色白名单。

对齐芯华章的 Governed Agent Team：
Requirement / Assertion / Emulation / Debug（+ 本仓库已有的 Coverage / Audit）。
"""
from __future__ import annotations

from typing import Dict, Set

from .actions import FORBIDDEN, DEFAULT_ACTIONS

ROLE_ACTIONS: Dict[str, Set[str]] = {
    # 需求智能体：读规格、产候选意图；不能直接改契约。
    "requirement": {
        "read_evidence", "generate_intent_candidate", "modify_intent",
        "confirm_intent", "change_assumption",
    },
    # 断言智能体：产候选断言/约束/测试，跑编译与形式。
    "assertion": {
        "read_evidence", "generate_assertion", "generate_constraint",
        "generate_test", "run_simulation", "run_formal",
    },
    # 仿真智能体：跑仿真/回归/仿真加速，读覆盖率。
    "emulation": {
        "read_evidence", "read_coverage", "run_simulation", "run_regression",
        "run_emulation",
    },
    # 调试智能体：提调试假设，读证据；不直接改判定。
    "debug": {
        "read_evidence", "read_coverage", "generate_debug_hypothesis",
        "run_simulation",
    },
    # 覆盖率智能体：解释证据、产解释候选。
    "coverage": {
        "read_evidence", "read_coverage", "generate_interpretation",
    },
    # 审计智能体：只读 + 产证据包；**没有审批权**。
    "audit": {"read_evidence", "read_coverage", "generate_interpretation"},
    # 工程师是治理节点：除破坏证据链的动作外都可请求（高风险仍需审批）。
    "engineer": set(),
}

_FORBIDDEN = {a for a, (d, _) in DEFAULT_ACTIONS.items() if d == FORBIDDEN}


def allowed_actions(role: str) -> Set[str]:
    role = str(role or "").strip().lower()
    if role == "engineer":
        return {a for a in DEFAULT_ACTIONS if a not in _FORBIDDEN}
    return set(ROLE_ACTIONS.get(role) or ())


def allowed(role: str, action: str) -> bool:
    """未知角色 / 未知动作 → 不允许（默认拒绝）。"""
    role = str(role or "").strip().lower()
    if action in _FORBIDDEN:
        return False
    if role in ("engineer", "system", "executor") and role != "":
        return True
    return action in allowed_actions(role)


def is_forbidden(action: str) -> bool:
    return action in _FORBIDDEN


__all__ = ["ROLE_ACTIONS", "allowed", "allowed_actions", "is_forbidden"]
