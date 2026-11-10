"""Coverage 专家的 LLM 工具循环节点（opt-in）。

只读覆盖率报告、列出文件、写一份 `coverage/agent_notes.md`；不跑 EDA、
不改覆盖数据。默认 off；`SIGNOFFAI_COVERAGE_LOOP=on` 才运行。
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict

import structlog

from src.layers.l2_orchestration.supervisor.coverage_tools import build_coverage_tools
from src.layers.l2_orchestration.supervisor.tool_loop import run_tool_loop

logger = structlog.get_logger()


def _enabled() -> bool:
    value = os.environ.get("SIGNOFFAI_COVERAGE_LOOP")
    if value is None:
        value = os.environ.get("SIGNOFFAI_AGENT_LOOP", "off")
    return value.strip().lower() in ("1", "on", "true", "yes")


def _goal(state) -> str:
    cov = getattr(state, "coverage", {}) or {}
    gaps = getattr(state, "gaps", []) or []
    return (
        "分析覆盖率结果与 gap，给出下一轮定向激励建议；只能读报告，"
        "最多写 coverage/agent_notes.md，不要伪造覆盖率。\n"
        f"coverage={json.dumps(cov, ensure_ascii=False, default=str)[:3000]}\n"
        f"gaps={json.dumps(gaps, ensure_ascii=False, default=str)[:3000]}"
    )


async def n_coverage_agent(state, config) -> Dict[str, Any]:
    if not _enabled():
        return {"coverage_agent_loop": {"skipped": True,
                                        "reason": "SIGNOFFAI_COVERAGE_LOOP!=on"}}
    root = getattr(state, "output_root", "output")
    try:
        result = await asyncio.to_thread(
            run_tool_loop, _goal(state), build_coverage_tools(root), max_steps=6)
        return {"coverage_agent_loop": result.to_dict()}
    except Exception as exc:                           # noqa: BLE001
        logger.warning(f"Coverage 工具循环失败，保留确定性管线: {exc}")
        return {"coverage_agent_loop": {"ok": False, "error": str(exc)}}


__all__ = ["n_coverage_agent"]
