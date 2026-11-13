"""Stage-as-tool wrappers —— 把 8 个 stage executor 暴露成 agent 可调用的工具。

与低层工具（read_file / auto_fix / check_static）的区别：
  · low-level tool：一个原子动作；
  · stage tool：跑完整个阶段（例如 design 的“拆 IP → 生成 RTL → 预检”）。

StageTool 只返回结构化摘要，不直接改父图状态；agent loop 看到结果后再决定
是否重试/继续。这样既保留 stage 的确定性实现，又让 agent 有“调用阶段”的入口。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Iterable, List, Sequence

from src.orchestration_plane.registry import card
from src.orchestration_plane.stage_policy import assert_stage
from src.orchestration_plane.l2.runtime import _run_agent


class StageTool:
    def __init__(self, agent: str, stage: str, rt: Any, state: Any):
        self.agent = agent
        self.stage = stage
        self.rt = rt
        self.state = state
        assert_stage(agent, stage)
        self.name = f"run_{stage}_stage"
        self.description = (
            f"运行 {stage} 阶段 executor（{card(agent).description}）；"
            "返回 phase 与 data 摘要，不直接改父图状态")

    def invoke(self, args: Dict[str, Any]) -> str:
        params = args.get("params") if isinstance(args, dict) else None
        if not isinstance(params, dict):
            params = {}

        async def _call():
            return await _run_agent(self.rt, self.state, self.stage,
                                    f"{self.stage}_stage", params)

        data, phase = asyncio.run(_call())
        return json.dumps({
            "stage": self.stage,
            "phase": phase,
            "data": data,
        }, ensure_ascii=False, default=str)[:20000]


def build_stage_tools(rt: Any, state: Any, agent: str,
                      only: Sequence[str] | None = None) -> List[StageTool]:
    allowed = set(only) if only else set(card(agent).stages)
    return [StageTool(agent, stage, rt, state)
            for stage in card(agent).stages if stage in allowed]


__all__ = ["StageTool", "build_stage_tools"]
