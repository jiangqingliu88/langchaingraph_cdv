"""Design 专家的 LLM 工具循环节点（opt-in）。

现有 DesignExecutor 仍是主路径；`SIGNOFFAI_DESIGN_LOOP=on` 时，如果它没产出
RTL，本节点用窄沙箱工具（只写 `<run>/rtl/*.sv`）让 LLM 自己读 spec、写 RTL、
check_rtl，再把控制权交回 design 子图的门禁。

没有 LLM key / 没写出 RTL 时只记录 `design_agent_loop`，不伪造成功。
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

import structlog

from src.agent_plane.specialists.design.tools import build_design_tools
from src.agent_plane.runtime.tool_loop import run_tool_loop

logger = structlog.get_logger()


def _enabled() -> bool:
    value = os.environ.get("SIGNOFFAI_DESIGN_LOOP")
    if value is None:
        value = os.environ.get("SIGNOFFAI_AGENT_LOOP", "off")
    return value.strip().lower() in ("1", "on", "true", "yes")


def _goal(state) -> str:
    spec = getattr(state, "spec", {}) or {}
    arch = getattr(state, "design_arch", {}) or {}
    return (
        "根据 spec 生成可综合 RTL。先用 list_rtl/read_file 看现状，"
        "用 write_file 写 <run>/rtl/*.sv，最后必须 check_rtl 验证；"
        "不要写 RTL 目录以外的文件。\n"
        f"spec={json.dumps(spec, ensure_ascii=False, default=str)[:5000]}\n"
        f"design_arch={json.dumps(arch, ensure_ascii=False, default=str)[:2000]}"
    )


async def n_design_agent(state, config) -> Dict[str, Any]:
    if not _enabled():
        return {"design_agent_loop": {"skipped": True,
                                      "reason": "SIGNOFFAI_DESIGN_LOOP!=on"}}
    if not getattr(state, "rtl_missing", False):
        return {"design_agent_loop": {"skipped": True,
                                      "reason": "rtl_present"}}
    root = getattr(state, "output_root", "output")
    try:
        result = await asyncio.to_thread(
            run_tool_loop, _goal(state), build_design_tools(root), max_steps=8)
        updates: Dict[str, Any] = {"design_agent_loop": result.to_dict()}
        rtl = Path(root) / "rtl"
        if result.ok and rtl.is_dir() and any(rtl.glob("*.sv")):
            updates["rtl_missing"] = False
            updates["phases"] = [{
                "name": "design_agent", "status": "passed",
                "tool_calls": len(result.tool_calls)}]
        return updates
    except Exception as exc:                           # noqa: BLE001
        logger.warning(f"Design 工具循环失败，回退确定性门禁: {exc}")
        return {"design_agent_loop": {"ok": False, "error": str(exc)}}


__all__ = ["n_design_agent"]
