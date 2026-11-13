"""模式路由 —— 用户只描述目标，系统选 Agent 或 Engine。"""
from __future__ import annotations

from typing import Any, Dict

from . import agent_mode, verify_mode


def run(goal: str, *, mode: str = "agent", **kwargs: Any) -> Dict[str, Any]:
    chosen = str(mode or "agent").strip().lower()
    if chosen in ("verify", "engine"):
        return verify_mode.run_goal(goal, **kwargs)
    return agent_mode.run_goal(goal, **kwargs)


def exit_code(result: Dict[str, Any], mode: str = "agent") -> int:
    chosen = str(mode or "agent").strip().lower()
    if chosen in ("verify", "engine"):
        return verify_mode.exit_code(result)
    return agent_mode.exit_code(result)


def render(result: Dict[str, Any], mode: str = "agent") -> None:
    chosen = str(mode or "agent").strip().lower()
    if chosen in ("verify", "engine"):
        verify_mode.render(result)
    else:
        agent_mode.render(result)


__all__ = ["run", "exit_code", "render"]
