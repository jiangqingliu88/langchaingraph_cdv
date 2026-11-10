"""Debug 专家的 LLM 工具循环节点。

默认 **关闭**（`SIGNOFFAI_AGENT_LOOP=on` 才启用）：现有 DebugExecutor 的确定性
五阶段管线仍然保留，工具循环是“专家自己选工具”的增量路径。关闭时节点只写
`skipped`，不改变旧行为；开启后失败也只会记录错误，后面的 `debug_functional`
仍可兜底。
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict

import structlog

from src.agents.runtime.tool_loop import run_tool_loop

logger = structlog.get_logger()


def _enabled() -> bool:
    return os.environ.get("SIGNOFFAI_AGENT_LOOP", "off").strip().lower() in (
        "1", "on", "true", "yes")


def _goal(state) -> str:
    regression = getattr(state, "regression", {}) or {}
    debug = getattr(state, "debug", {}) or {}
    return (
        "诊断并修复当前回归失败。先读日志/定位，再决定是否 auto_fix；"
        "只有工具返回的证据支持时才改代码。\n"
        f"regression={json.dumps(regression, ensure_ascii=False, default=str)[:3000]}\n"
        f"debug={json.dumps(debug, ensure_ascii=False, default=str)[:2000]}"
    )


async def n_debug_agent(state, config) -> Dict[str, Any]:
    if not _enabled():
        return {"debug_agent_loop": {"skipped": True,
                                     "reason": "SIGNOFFAI_AGENT_LOOP!=on"}}
    try:
        from src.executors.debug.tools.main import DebugTools

        tools = DebugTools().get_tools()
        result = await asyncio.to_thread(
            run_tool_loop, _goal(state), tools, max_steps=6)
        return {"debug_agent_loop": result.to_dict()}
    except Exception as exc:                           # noqa: BLE001
        logger.warning(f"Debug 工具循环失败，回退确定性管线: {exc}")
        return {"debug_agent_loop": {"ok": False, "error": str(exc)}}


__all__ = ["n_debug_agent"]
