"""阶段执行器服务 —— 给长循环 agent 的 `run_stage` 工具提供单阶段执行入口。

复用 `PipelineExecutionService.run_single_agent`（8 个 executor 的公开实现），
不经过 supervisor 图。EDA/证据由 executor 自己落盘，agent 再读结果。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

STAGES = ("front", "design", "model", "verify", "ops",
          "coverage", "debug", "audit")


def run_stage_executor(role: str, *, input_text: str = "",
                    output_dir: str | Path | None = None,
                    ctx: Dict[str, Any] | None = None,
                    params: Dict[str, Any] | None = None,
                    timeout_s: int | None = None) -> Dict[str, Any]:
    role = str(role or "").strip().lower()
    if role not in STAGES:
        return {"ok": False, "error": f"未知 stage：{role}（可选 {', '.join(STAGES)}）"}

    async def _run() -> Dict[str, Any]:
        from src.orchestration_plane.l2.execution import PipelineExecutionService
        service = PipelineExecutionService.get_instance()
        await service.initialize_agents()
        return await service.run_single_agent(
            role, input_text, output_dir=str(output_dir) if output_dir else None,
            ctx=ctx, params=params)

    try:
        result = asyncio.run(asyncio.wait_for(_run(), timeout_s)) if timeout_s else asyncio.run(_run())
    except (TimeoutError, asyncio.TimeoutError):
        return {"ok": False, "role": role, "error": f"超时 {timeout_s}s"}
    except Exception as exc:                      # noqa: BLE001 单阶段失败要响亮返回
        return {"ok": False, "role": role, "error": str(exc)}
    result = dict(result or {})
    result.setdefault("ok", bool(result.get("success")))
    if not result.get("ok") and not result.get("error"):
        result["error"] = f"{role} stage 未完成（success=False，未提供 error）"
    result["role"] = role
    return result


__all__ = ["STAGES", "run_stage_executor"]
