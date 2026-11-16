"""十个独立 ReAct 角色的包注册与兼容别名（不是一个共享 Agent 的别名集）。"""

from __future__ import annotations

import importlib
from typing import Any

# package / exported class。它们位于既有 agent_plane 内部的不同 Domain 子目录，
# 不是新的架构平面，也不意味着新 Agent 自动获得其名称所暗示的 EDA 能力。
ROLE_LOCATIONS: dict[str, tuple[str, str]] = {
    "mental_model_agent": ("design_understanding/mental_model_agent", "MentalModelAgent"),
    "simulation_agent": ("design_verification/simulation_agent", "SimulationAgent"),
    "lint_autofix": ("design_signoff/lint_autofix", "LintAutoFixAgent"),
    "rtl_upgrade_agent": ("design_generation/rtl_upgrade_agent", "RTLUpgradeAgent"),
    "rtl_early_estimation_agent": ("design_generation/rtl_early_estimation_agent", "RTLEarlyEstimationAgent"),
    "formal_agent": ("verification/formal_agent", "FormalAgent"),
    "functional_coverage_agent": ("verification/functional_coverage_agent", "FunctionalCoverageAgent"),
    "test_plan_agent": ("verification/test_plan_agent", "TestPlanAgent"),
    "uvm_coding_agent": ("verification/uvm_coding_agent", "UVMCodingAgent"),
    "dv_debug_agent": ("verification/dv_debug_agent", "DVDebugAgent"),
}

# 只承接旧 key 到新 class，不把多个 alias 当成多个执行实例。
LEGACY_ALIASES = {
    "mental": "mental_model_agent",
    "formal": "formal_agent",
    "unit_test": "simulation_agent",
    "unit_testing": "simulation_agent",
    "simulation-agent": "simulation_agent",
    "rtl_designer": "rtl_upgrade_agent",
    "uvm": "uvm_coding_agent",
    "functional_coverage": "functional_coverage_agent",
    "dv_debug": "dv_debug_agent",
}


def canonical_role(role_id: str) -> str:
    return LEGACY_ALIASES.get(role_id, role_id)


def _entry(role_id: str) -> tuple[str, type]:
    role_id = canonical_role(role_id)
    if role_id not in ROLE_LOCATIONS:
        raise KeyError(f"未登记的 ReAct Agent：{role_id}")
    relative, class_name = ROLE_LOCATIONS[role_id]
    module = importlib.import_module(f"src.agent_plane.{relative.replace('/', '.')}.agent")
    return getattr(module, class_name), class_name


def create_agent(role_id: str, *, workspace_root=".", **kwargs):
    """每次构造独立 Graph 与 RoleSpec，不复用一个可跨角色切换状态的 Agent。"""
    cls, _ = _entry(role_id)
    return cls(workspace_root=workspace_root, **kwargs)


def role_metadata() -> list[dict[str, Any]]:
    """返回各 Agent 自己的 RoleSpec；这里不运行 loop 或模型。"""
    rows = []
    for role_id in ROLE_LOCATIONS:
        cls, _ = _entry(role_id)
        spec = cls.ROLE
        rows.append(
            {
                "role_id": role_id,
                "domain": spec.domain,
                "title": spec.title,
                "package": f"src/agent_plane/{ROLE_LOCATIONS[role_id][0]}/",
                "class": cls.__name__,
                "inputs": list(spec.inputs),
                "responsibility": spec.responsibility,
                "instructions": spec.instructions,
                "allowed_tools": list(spec.allowed_tools),
                "max_steps": spec.max_steps,
                "write_allowed": spec.write_allowed,
            }
        )
    return rows


__all__ = ["ROLE_LOCATIONS", "LEGACY_ALIASES", "canonical_role", "create_agent", "role_metadata"]
