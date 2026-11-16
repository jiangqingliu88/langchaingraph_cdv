"""项目产物工作区：ChipStack 五层目录契约 + 结构化索引，不是 Agent 平面。"""

from .chipstack_workspace import ChipStackWorkspace, PublishedWorkspace, read_workspace_runs
from .project_layout import (
    AGENT_ARTIFACT_DIRS,
    ARTIFACT_DIRNAME,
    ARTIFACT_DIRS_SPEC,
    DOMAIN_ARTIFACT_HINTS,
    Layer,
    ProjectLayout,
    RunLayout,
    agent_artifact_dir,
    default_home,
    install_root,
    run_id_now,
    run_session,
    safe_name,
)

__all__ = [
    "ChipStackWorkspace",
    "PublishedWorkspace",
    "read_workspace_runs",
    "ProjectLayout",
    "RunLayout",
    "Layer",
    "run_session",
    "safe_name",
    "run_id_now",
    "agent_artifact_dir",
    "default_home",
    "install_root",
    "ARTIFACT_DIRNAME",
    "ARTIFACT_DIRS_SPEC",
    "AGENT_ARTIFACT_DIRS",
    "DOMAIN_ARTIFACT_HINTS",
]
