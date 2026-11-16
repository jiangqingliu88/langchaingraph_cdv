"""`rtl_designer` 的对话入口（走统一 Harness / 模式适配层）。"""

from __future__ import annotations

from typing import Any

from src.agent_plane.specialists.chat_common import chat as _chat

AGENT_ID = "rtl_designer"


def chat(prompt: str, **kwargs: Any) -> dict[str, Any]:
    """一次对话 turn；workspace / session_id / frontend 原样透传。"""
    return _chat(AGENT_ID, prompt, **kwargs)


__all__ = ["AGENT_ID", "chat"]
