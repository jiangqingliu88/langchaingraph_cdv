"""Stage 调用策略 —— 把 agent card 变成运行期可检查的规则。"""
from __future__ import annotations

from .registry import AgentCard, card


class StagePolicyError(PermissionError):
    pass


def can_call_stage(agent: str, stage: str) -> bool:
    return stage in card(agent).stages


def can_use_tool(agent: str, tool: str) -> bool:
    c: AgentCard = card(agent)
    return tool in c.tools


def assert_stage(agent: str, stage: str) -> None:
    if not can_call_stage(agent, stage):
        raise StagePolicyError(f"{agent} 无权调用 stage {stage!r}")


def assert_tool(agent: str, tool: str) -> None:
    if not can_use_tool(agent, tool):
        raise StagePolicyError(f"{agent} 无权使用 tool {tool!r}")


def should_ask_human(agent: str, attempts: int) -> bool:
    limit = card(agent).requires_human_after
    return bool(limit) and attempts >= limit


__all__ = [
    "StagePolicyError", "can_call_stage", "can_use_tool", "assert_stage",
    "assert_tool", "should_ask_human",
]
