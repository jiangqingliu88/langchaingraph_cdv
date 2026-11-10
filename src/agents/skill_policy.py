"""Skill 调用策略 —— 把 agent card 变成运行期可检查的规则。"""
from __future__ import annotations

from .registry import AgentCard, card


class SkillPolicyError(PermissionError):
    pass


def can_call_skill(agent: str, skill: str) -> bool:
    return skill in card(agent).skills


def can_use_tool(agent: str, tool: str) -> bool:
    c: AgentCard = card(agent)
    return tool in c.tools


def assert_skill(agent: str, skill: str) -> None:
    if not can_call_skill(agent, skill):
        raise SkillPolicyError(f"{agent} 无权调用 skill {skill!r}")


def assert_tool(agent: str, tool: str) -> None:
    if not can_use_tool(agent, tool):
        raise SkillPolicyError(f"{agent} 无权使用 tool {tool!r}")


def should_ask_human(agent: str, attempts: int) -> bool:
    limit = card(agent).requires_human_after
    return bool(limit) and attempts >= limit


__all__ = [
    "SkillPolicyError", "can_call_skill", "can_use_tool", "assert_skill",
    "assert_tool", "should_ask_human",
]
