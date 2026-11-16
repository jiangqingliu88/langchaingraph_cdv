"""Agent Plane facade (Architecture 4.0).

Implementation lives in `src/agent_plane/{reaction,domains,runtime,memory,
planner,collaboration}/`.

**这里是惰性门面**：`agent_plane.domains` 是目录架构的权威注册表，CLI/GUI 都
会 import 它；如果本文件在 import 时就把 `agents` SDK、Workbench 模式等重依赖
全部拉起来，那么「只想看工程目录」的场景也会被缺失的可选依赖挡住。所以所有
导出改成 PEP 562 的 `__getattr__` 按需加载，`from src.agent_plane import X`
的用法保持不变。
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY = {
    # runtime / memory / planner / collaboration
    "Harness": ("src.agent_plane.runtime.harness", "Harness"),
    "HarnessConfig": ("src.agent_plane.runtime.harness", "HarnessConfig"),
    "ProjectMemory": ("src.agent_plane.memory", "ProjectMemory"),
    "TaskStore": ("src.agent_plane.memory", "TaskStore"),
    "render_working": ("src.agent_plane.memory", "render_working"),
    "working_summary": ("src.agent_plane.memory", "working_summary"),
    "acceptance_met": ("src.agent_plane.planner", "acceptance_met"),
    "downstream_of": ("src.agent_plane.planner", "downstream_of"),
    "layers": ("src.agent_plane.planner", "layers"),
    "new_plan": ("src.agent_plane.planner", "new_plan"),
    "replan": ("src.agent_plane.planner", "replan"),
    "should_replan": ("src.agent_plane.planner", "should_replan"),
    "AGENT_TYPES": ("src.agent_plane.collaboration", "AGENT_TYPES"),
    "SubagentContract": ("src.agent_plane.collaboration", "SubagentContract"),
    "SubagentManager": ("src.agent_plane.collaboration", "SubagentManager"),
    "SubagentResult": ("src.agent_plane.collaboration", "SubagentResult"),
    "build_contract": ("src.agent_plane.collaboration", "build_contract"),
    # workbench / reaction
    "run_goal": ("src.workbench.modes.agent_mode", "run_goal"),
    "create_react_agent": ("src.agent_plane.reaction.registry", "create_agent"),
    "react_agent_metadata": ("src.agent_plane.reaction.registry", "role_metadata"),
    # 目录架构注册表（不依赖 SDK）
    "AGENT_SPECS": ("src.agent_plane.domains", "AGENTS"),
    "AGENT_DOMAINS": ("src.agent_plane.domains", "DOMAINS"),
    "agent_spec": ("src.agent_plane.domains", "agent_spec"),
    "all_agents": ("src.agent_plane.domains", "all_agents"),
    "all_domains": ("src.agent_plane.domains", "all_domains"),
    "agent_artifact_dir": ("src.agent_plane.domains", "artifact_dir"),
    "create_domain_agent": ("src.agent_plane.domains", "create_agent"),
    "domain_of": ("src.agent_plane.domains", "domain_of"),
    "expected_artifact_dirs": ("src.agent_plane.domains", "expected_artifact_dirs"),
    "agent_layout_rows": ("src.agent_plane.domains", "layout_rows"),
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    value = getattr(import_module(module_name), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(_LAZY)
