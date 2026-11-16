"""9 个 agent 共用的对话入口。

每个 `specialists/<agent>/chat.py` 只声明自己的 `AGENT_ID`，真正的模式解析、
Harness 调用、审批配置统一在这里 —— 避免 9 个目录各写一份对话逻辑。
"""

from __future__ import annotations

from typing import Any


def chat(
    agent_id: str, prompt: str, *, workspace: str | None = None, session_id: str | None = None, frontend: str = "cli"
) -> dict[str, Any]:
    """一次对话 turn（经 workbench 的模式适配层，不重复实现 Agent）。"""
    from src.workbench.modes.agent_modes import get_mode
    from src.workbench.modes.interaction import turn

    preset = get_mode(agent_id)
    return turn(
        prompt,
        mode=preset.interaction,
        agent_mode=preset.id,
        workspace=workspace,
        session_id=session_id,
        frontend=frontend,
    )


__all__ = ["chat"]
