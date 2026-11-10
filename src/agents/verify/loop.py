"""Verify 专家的 LLM 工具循环节点（opt-in）。

复用既有 UVM 工具（find_spec_yaml / jinja_render / check_static /
read_file / write_file），让 Verify 在确定性生成之后自己检查并修补环境。
默认 off；`SIGNOFFAI_VERIFY_LOOP=on` 才运行，失败只记录、不阻断确定性管线。
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
    value = os.environ.get("SIGNOFFAI_VERIFY_LOOP")
    if value is None:
        value = os.environ.get("SIGNOFFAI_AGENT_LOOP", "off")
    return value.strip().lower() in ("1", "on", "true", "yes")


def _goal(state) -> str:
    spec = getattr(state, "spec", {}) or {}
    tests = getattr(state, "tests", {}) or {}
    return (
        "检查并修补 UVM 验证环境：先 find_spec_yaml / check_static，"
        "必要时 jinja_render，再 check_static；不要写 <run> 之外的文件。\n"
        f"spec={json.dumps(spec, ensure_ascii=False, default=str)[:4000]}\n"
        f"tests={json.dumps(tests, ensure_ascii=False, default=str)[:2000]}"
    )


async def n_verify_agent(state, config) -> Dict[str, Any]:
    if not _enabled():
        return {"verify_agent_loop": {"skipped": True,
                                      "reason": "SIGNOFFAI_VERIFY_LOOP!=on"}}
    output_dir = getattr(state, "output_root", "output")
    try:
        from src.tools.generation.uvm_tools.agent_tools import (
            _uvm_ctx, check_static, find_spec_yaml, jinja_render,
            read_file, write_file,
        )

        _uvm_ctx.set(output_dir=output_dir, agents=[],
                     env_name=f"{(getattr(state, 'spec', {}) or {}).get('design_name', 'dut')}_env")
        tools = [find_spec_yaml, jinja_render, check_static, read_file, write_file]
        result = await asyncio.to_thread(
            run_tool_loop, _goal(state), tools, max_steps=8)
        return {"verify_agent_loop": result.to_dict()}
    except Exception as exc:                           # noqa: BLE001
        logger.warning(f"Verify 工具循环失败，保留确定性管线: {exc}")
        return {"verify_agent_loop": {"ok": False, "error": str(exc)}}


__all__ = ["n_verify_agent"]
