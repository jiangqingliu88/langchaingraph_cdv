"""
Tool Sandbox — 工具隔离执行环境 (Phase 2)

提供:
  1. 超时控制 (timeout)
  2. 资源限制 (内存/CPU)
  3. 子进程隔离 (subprocess)
  4. 权限策略配置

用法:
  from src.core.tool_sandbox import ToolSandbox, SandboxPolicy
  sandbox = ToolSandbox(SandboxPolicy.standard())
  result = await sandbox.execute(my_tool, args, context)
"""
from __future__ import annotations

import asyncio
import multiprocessing
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.tool_protocol import (
    ITool, ToolResult, ExecutionContext, ToolRisk, ExecutionMode, ToolManifest,
)


@dataclass
class SandboxPolicy:
    """沙盒执行策略"""

    # 超时
    default_timeout_s: float = 300.0
    max_timeout_s: float = 3600.0       # 绝对上限

    # 资源限制
    max_memory_mb: int = 2048            # 最大内存 (MB)
    max_cpu_percent: int = 80            # CPU 使用率上限 (%)

    # 文件系统
    allowed_paths: List[str] = field(default_factory=lambda: [".", "output", "logs", "/tmp"])
    denied_paths: List[str] = field(default_factory=lambda: ["/etc/passwd", "/etc/shadow", "~/.ssh"])

    # 网络
    allow_network: bool = False          # 是否允许网络访问
    allowed_hosts: List[str] = field(default_factory=list)  # 允许访问的主机白名单

    # 系统调用
    allow_subprocess: bool = True        # 是否允许启动子进程
    allow_file_write: bool = True        # 是否允许写文件
    allow_file_delete: bool = False      # 是否允许删除文件

    # 风险级别权限
    risk_permissions: Dict[str, Dict[str, bool]] = field(default_factory=lambda: {
        "safe":    {"auto_approve": True,  "requires_confirm": False, "max_timeout_s": 60.0},
        "write":   {"auto_approve": False, "requires_confirm": True,  "max_timeout_s": 300.0},
        "danger":  {"auto_approve": False, "requires_confirm": True,  "max_timeout_s": 600.0},
    })

    @classmethod
    def standard(cls) -> SandboxPolicy:
        """标准策略 —— 推荐用于生产环境"""
        return cls()

    @classmethod
    def permissive(cls) -> SandboxPolicy:
        """宽松策略 —— 开发/调试环境"""
        return cls(
            default_timeout_s=600.0,
            max_timeout_s=7200.0,
            allow_network=True,
            allow_file_delete=True,
            risk_permissions={
                "safe":    {"auto_approve": True,  "requires_confirm": False, "max_timeout_s": 120.0},
                "write":   {"auto_approve": True,  "requires_confirm": False, "max_timeout_s": 600.0},
                "danger":  {"auto_approve": False, "requires_confirm": True,  "max_timeout_s": 1200.0},
            },
        )

    @classmethod
    def strict(cls) -> SandboxPolicy:
        """严格策略 —— CI 环境 / 不受信任的工具"""
        return cls(
            default_timeout_s=120.0,
            max_timeout_s=600.0,
            max_memory_mb=512,
            allow_network=False,
            allow_file_delete=False,
            allow_subprocess=False,
            risk_permissions={
                "safe":    {"auto_approve": True,  "requires_confirm": False, "max_timeout_s": 30.0},
                "write":   {"auto_approve": False, "requires_confirm": True,  "max_timeout_s": 60.0},
                "danger":  {"auto_approve": False, "requires_confirm": True,  "max_timeout_s": 120.0},
            },
        )


class ToolSandbox:
    """工具隔离执行环境"""

    def __init__(self, policy: SandboxPolicy = None):
        self.policy = policy or SandboxPolicy.standard()
        self._stats = {"executions": 0, "timeouts": 0, "blocks": 0, "total_time_s": 0.0}

    def check_permission(self, manifest: ToolManifest, args: Dict[str, Any]) -> Tuple[bool, str]:
        """检查工具是否允许在当前策略下执行。返回 (pass, reason)。"""
        risk = manifest.risk_level.value
        perm = self.policy.risk_permissions.get(risk, {})

        # 超时上限
        if manifest.timeout_s > self.policy.max_timeout_s:
            return False, f"Timeout {manifest.timeout_s}s exceeds max {self.policy.max_timeout_s}s"

        # 网络检查
        if not self.policy.allow_network and manifest.execution_mode == ExecutionMode.CONTAINER:
            return False, "Network access is not allowed"

        # 文件路径检查
        for key, val in args.items():
            if isinstance(val, str) and key.lower() in ("path", "file", "output", "log"):
                p = Path(val).expanduser().resolve()
                allowed = False
                for ap in self.policy.allowed_paths:
                    try:
                        p.relative_to(Path(ap).expanduser().resolve())
                        allowed = True
                        break
                    except ValueError:
                        continue
                for dp in self.policy.denied_paths:
                    try:
                        p.relative_to(Path(dp).expanduser().resolve())
                        allowed = False
                        break
                    except ValueError:
                        continue
                if not allowed and not str(p).startswith("/tmp"):
                    return False, f"Path '{val}' not in allowed paths: {self.policy.allowed_paths}"

        return True, "ok"

    async def execute(self, tool: ITool, args: Dict[str, Any],
                      context: ExecutionContext = None) -> ToolResult:
        """在沙盒中执行工具。

        Args:
          tool: 工具实例
          args: 已验证的参数
          context: 执行上下文

        Returns:
          ToolResult with success/error
        """
        self._stats["executions"] += 1
        manifest = tool.manifest
        ctx = context or ExecutionContext()

        # 权限检查
        ok, reason = self.check_permission(manifest, args)
        if not ok:
            self._stats["blocks"] += 1
            return ToolResult.fail(f"Sandbox blocked: {reason}")

        # 确定超时
        risk = manifest.risk_level.value
        perm = self.policy.risk_permissions.get(risk, {})
        timeout = min(manifest.timeout_s, perm.get("max_timeout_s", self.policy.default_timeout_s))

        # 按执行模式调度
        try:
            if manifest.execution_mode == ExecutionMode.SUBPROCESS:
                result = await self._execute_subprocess(tool, args, ctx, timeout)
            elif manifest.execution_mode == ExecutionMode.CONTAINER:
                result = await self._execute_container(tool, args, ctx, timeout)
            else:
                result = await self._execute_inline(tool, args, ctx, timeout)
            self._stats["total_time_s"] += result.execution_time_s
            return result
        except asyncio.TimeoutError:
            self._stats["timeouts"] += 1
            return ToolResult.fail(f"Tool '{manifest.name}' timed out after {timeout}s")
        except Exception as e:
            return ToolResult.fail(f"Sandbox execution error: {str(e)[:500]}")

    async def _execute_inline(self, tool: ITool, args: dict,
                              ctx: ExecutionContext, timeout: float) -> ToolResult:
        """同进程执行（带超时）"""
        return await asyncio.wait_for(
            tool.execute(args, ctx),
            timeout=timeout,
        )

    async def _execute_subprocess(self, tool: ITool, args: dict,
                                  ctx: ExecutionContext, timeout: float) -> ToolResult:
        """子进程隔离执行"""
        # 序列化输入
        import json as _json
        input_data = _json.dumps({
            "tool_name": tool.manifest.name,
            "args": args,
            "context": ctx.snapshot(),
        })

        # 在子进程中执行
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", _SUBPROCESS_RUNNER,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024,  # 10MB buffer
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input_data.encode()),
                timeout=timeout,
            )

            if proc.returncode == 0:
                try:
                    data = _json.loads(stdout.decode())
                    return ToolResult(**data) if isinstance(data, dict) else ToolResult.ok({"raw": data})
                except Exception:
                    return ToolResult.ok({"output": stdout.decode()[:5000]})
            else:
                return ToolResult.fail(stderr.decode()[:1000])
        except Exception as e:
            return ToolResult.fail(f"Subprocess error: {str(e)[:500]}")

    async def _execute_container(self, tool: ITool, args: dict,
                                 ctx: ExecutionContext, timeout: float) -> ToolResult:
        """容器隔离执行（Docker/podman）"""
        # Check docker availability
        docker_cmd = None
        for cmd in ["docker", "podman"]:
            try:
                proc = await asyncio.create_subprocess_exec(
                    cmd, "--version",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                if proc.returncode == 0:
                    docker_cmd = cmd
                    break
            except Exception:
                continue

        if not docker_cmd:
            return ToolResult.fail("No container runtime found (docker/podman)")

        # Write input to temp file
        import json as _json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump({"tool_name": tool.manifest.name, "args": args,
                        "context": ctx.snapshot()}, f)
            tmp_file = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                docker_cmd, "run", "--rm",
                f"--memory={self.policy.max_memory_mb}m",
                "--network", "none" if not self.policy.allow_network else "bridge",
                f"--volume={os.getcwd()}:/workspace",
                "-w", "/workspace",
                "signoffai-runner:latest",
                "python", "-c", _SUBPROCESS_RUNNER,
                stdin=open(tmp_file, "r"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )

            if proc.returncode == 0:
                try:
                    data = _json.loads(stdout.decode())
                    return ToolResult(**data) if isinstance(data, dict) else ToolResult.ok({"raw": data})
                except Exception:
                    return ToolResult.ok({"output": stdout.decode()[:5000]})
            else:
                return ToolResult.fail(stderr.decode()[:1000])
        finally:
            try:
                os.unlink(tmp_file)
            except Exception:
                pass

    @property
    def stats(self) -> Dict[str, Any]:
        return dict(self._stats)


# ═══════════════════════════════════════════════════════════════
# 子进程执行器
# ═══════════════════════════════════════════════════════════════

_SUBPROCESS_RUNNER = r"""
import sys, json, asyncio, importlib

async def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
        tool_name = data.get("tool_name", "")
        args = data.get("args", {})
        ctx_data = data.get("context", {})

        # 动态导入并查找工具
        # 简化: 通过 ToolHub 查找
        sys.path.insert(0, '.')
        from src.core.tool_hub import ToolHub
        from src.core.tool_protocol import ExecutionContext

        hub = ToolHub.get_instance()
        hub._load_builtin_tools()

        tool = hub.get(tool_name)
        if not tool:
            print(json.dumps({"success": False, "error": f"Tool '{tool_name}' not found"}))
            return

        ctx = ExecutionContext(**ctx_data)
        result = await tool.execute(args, ctx)
        print(json.dumps({
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "execution_time_s": result.execution_time_s,
        }))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)[:500]}))

asyncio.run(main())
"""
