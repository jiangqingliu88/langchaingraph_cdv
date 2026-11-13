"""Agent Mode —— 长循环 Agent 的统一 facade。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.app.services import agent_mode_service as _service


def run_goal(goal: str, *, workspace: Optional[str] = None,
             session_id: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    return _service.agent_turn(goal, workspace=workspace,
                               session_id=session_id, **kwargs)


def resume_turn(session_id: str, **kwargs: Any) -> Dict[str, Any]:
    return _service.resume_turn(session_id, **kwargs)


def render(result: Dict[str, Any]) -> None:
    _service.render(result)


def exit_code(result: Dict[str, Any]) -> int:
    return int(result.get("exit_code") or 0)


__all__ = ["run_goal", "resume_turn", "render", "exit_code"]
