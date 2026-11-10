"""Skill-as-tool wrappers —— 把 8 个 stage skill 暴露成 agent 可调用的工具。

与低层工具（read_file / auto_fix / check_static）的区别：
  · low-level tool：一个原子动作；
  · skill tool：跑完整个阶段（例如 design 的“拆 IP → 生成 RTL → 预检”）。

SkillTool 只返回结构化摘要，不直接改父图状态；agent loop 看到结果后再决定
是否重试/继续。这样既保留 skill 的确定性实现，又让 agent 有“调用技能”的入口。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Iterable, List, Sequence

from src.agents.registry import card
from src.agents.skill_policy import assert_skill
from src.layers.l2_orchestration.runtime import _run_agent


class SkillTool:
    def __init__(self, agent: str, skill: str, rt: Any, state: Any):
        self.agent = agent
        self.skill = skill
        self.rt = rt
        self.state = state
        assert_skill(agent, skill)
        self.name = f"run_{skill}_skill"
        self.description = (
            f"运行 {skill} 阶段 skill（{card(agent).description}）；"
            "返回 phase 与 data 摘要，不直接改父图状态")

    def invoke(self, args: Dict[str, Any]) -> str:
        params = args.get("params") if isinstance(args, dict) else None
        if not isinstance(params, dict):
            params = {}

        async def _call():
            return await _run_agent(self.rt, self.state, self.skill,
                                    f"{self.skill}_skill", params)

        data, phase = asyncio.run(_call())
        return json.dumps({
            "skill": self.skill,
            "phase": phase,
            "data": data,
        }, ensure_ascii=False, default=str)[:20000]


def build_skill_tools(rt: Any, state: Any, agent: str,
                      only: Sequence[str] | None = None) -> List[SkillTool]:
    allowed = set(only) if only else set(card(agent).skills)
    return [SkillTool(agent, skill, rt, state)
            for skill in card(agent).skills if skill in allowed]


__all__ = ["SkillTool", "build_skill_tools"]
