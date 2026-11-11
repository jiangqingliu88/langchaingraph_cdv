"""Agent 权限 1.0 — 角色只能调用授权 Module/Task。"""
from __future__ import annotations

from .registry import AgentSpec


class PermissionDenied(PermissionError):
    pass


def assert_task(spec: AgentSpec, task_type: str) -> None:
    if task_type not in spec.tasks:
        raise PermissionDenied(
            f"agent {spec.name} cannot run task {task_type!r}; "
            f"allowed={list(spec.tasks)}")


def assert_write(spec: AgentSpec) -> None:
    if not spec.can_write:
        raise PermissionDenied(f"agent {spec.name} is read-only")
