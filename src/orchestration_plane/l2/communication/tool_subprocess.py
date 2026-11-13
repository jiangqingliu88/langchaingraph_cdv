"""
工具 Stdio 进程隔离 —— 把工具调用隔离到独立子进程（MCP Stdio 传输风格）。

借鉴 claw-code 的 MCP Stdio 传输：每个工具是独立进程，通过 stdin/stdout 传 JSON。
好处：
  1. 工具崩溃（如 EDA 工具 OOM/段错误）不拖垮主流程；
  2. 工具可独立复现（对应"每个 Tool 独立脚本"原则）；
  3. 天然支持并行。

用法:
    from src.orchestration_plane.l2.communication.tool_subprocess import run_tool_in_subprocess
    result = run_tool_in_subprocess("regression.run_golden", {"output_dir": "..."})
    # → {"success": bool, "data": {...}, "error": "..."}
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict


def run_tool_in_subprocess(tool_name: str, args: Dict[str, Any],
                           timeout_s: float = 600.0) -> Dict[str, Any]:
    """在独立子进程执行工具，通过 stdin/stdout 传 JSON。

    worker 进程崩溃（非 0 退出）→ 返回 {success: False, error}，不抛异常。
    """
    req = json.dumps({"tool": tool_name, "args": args}, ensure_ascii=False)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "src.orchestration_plane.l2.communication.tool_worker"],
            input=req, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_s,
        )
        if r.returncode != 0:
            return {"success": False, "error": f"worker crashed (rc={r.returncode}): {r.stderr[:300]}"}
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            # worker 的 stdout 可能被 structlog 日志 / print 污染，提取最后一个 JSON 对象
            for line in reversed(r.stdout.strip().splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        return json.loads(line)
                    except json.JSONDecodeError:
                        continue
            return {"success": False, "error": f"worker 输出非法 JSON: {r.stdout[:200]}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"工具 '{tool_name}' 超时 ({timeout_s}s)"}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}


def worker_main():
    """子进程入口：从 stdin 读 JSON 请求，执行工具，向 stdout 写 JSON 响应。"""
    import asyncio

    try:
        req = json.loads(sys.stdin.read())
    except Exception as e:
        print(json.dumps({"success": False, "error": f"bad request: {e}"}, ensure_ascii=False))
        return

    tool_name = req.get("tool", "")
    args = req.get("args", {})

    async def _run():
        from src.orchestration_plane.l2.communication.tool_hub import ToolHub
        from src.orchestration_plane.l2.regression_tools.regression_tool import (
            RegressionRunTool, CoverageCollectTool)
        hub = ToolHub.get_instance()
        # 懒注册（worker 进程独立，需重新注册工具）
        if hub.get(tool_name) is None:
            if tool_name == "regression.run":
                hub.register(RegressionRunTool(), ["ops", "guardian"])
            elif tool_name == "coverage.collect":
                hub.register(CoverageCollectTool(), ["coverage", "ops"])
        result = await hub.invoke(tool_name, args)
        return {"success": result.success, "data": result.data, "error": result.error}

    try:
        result = asyncio.run(_run())
    except Exception as e:
        result = {"success": False, "error": str(e)[:500]}

    print(json.dumps(result, ensure_ascii=False, default=str))
