"""命令 / 路径白名单。

默认 `monitor`：**记录但不拦**。EDA 环境千差万别，一上来就 enforce 会把本来
能跑的回归拦死；先把"越界调用"变成可见事实，再按模块收紧。设
`SIGNOFFAI_CMD_ALLOWLIST=enforce` 才真正拒绝。
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ENV_MODE = "SIGNOFFAI_CMD_ALLOWLIST"
ENV_ROOTS = "SIGNOFFAI_CMD_ROOTS"

#: 常见 EDA / 构建 / 脚本工具。新增工具在这里加，别在调用点一处处放开。
DEFAULT_TOOLS = frozenset({
    "vlog", "vopt", "vsim", "vcover", "vcs", "simv", "verdi", "xrun",
    "iverilog", "vvp", "verilator", "yosys", "make", "cmake",
    "bash", "sh", "cmd", "powershell", "pwsh",
    "python", "python3", "py", "git", "grep", "find", "cat", "ls", "dir",
    "taskkill", "wmic", "sleep", "true", "echo",
})

_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_PATHISH_RE = re.compile(r"(^[\\/]|^\.\.?[\\/]|[\\/]\.\.([\\/]|$)|\s)")


def _norm_tool(tool: str) -> str:
    name = Path(str(tool)).name.lower()
    for suffix in (".exe", ".bat", ".cmd", ".ps1"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _looks_pathish(arg: str) -> bool:
    if not arg or arg.startswith("-"):
        return False
    return bool(_DRIVE_RE.match(arg) or _PATHISH_RE.search(arg))


def _is_within(path: Path, roots: Sequence[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


@dataclass
class CommandPolicy:
    mode: str = "monitor"                 # monitor | enforce | off
    allow_tools: frozenset = field(default_factory=lambda: DEFAULT_TOOLS)
    allow_paths: bool = True
    strict_path: bool = False
    extra_roots: Tuple[Path, ...] = ()

    @classmethod
    def from_env(cls) -> "CommandPolicy":
        mode = os.environ.get(ENV_MODE, "monitor").strip().lower()
        if mode not in ("monitor", "enforce", "off"):
            mode = "monitor"
        raw_roots = os.environ.get(ENV_ROOTS, "")
        roots = tuple(Path(p).expanduser() for p in raw_roots.split(os.pathsep) if p.strip())
        return cls(mode=mode, extra_roots=roots)

    def _violation(self, argv: Sequence[str], cwd: Optional[Path],
                   run_dir: Optional[Path]) -> str:
        if not argv:
            return "空命令"
        tool = _norm_tool(argv[0])
        if tool not in self.allow_tools:
            return f"工具 {tool!r} 不在白名单"
        if tool in ("python", "python3", "py") and "-c" in argv[1:]:
            return "python -c 内联代码不在白名单策略内"
        if not self.allow_paths:
            return ""
        roots = [Path(cwd or os.getcwd())]
        if run_dir is not None:
            roots.append(Path(run_dir))
        roots.extend(self.extra_roots)
        for arg in argv[1:]:
            if not _looks_pathish(arg):
                continue
            candidate = Path(arg)
            if not candidate.is_absolute():
                candidate = roots[0] / candidate
            if not _is_within(candidate, roots):
                return f"路径 {arg!r} 越出允许根 {[str(r) for r in roots]}"
        return ""

    def check(self, argv: Sequence[str], *, cwd: Optional[Path] = None,
              run_dir: Optional[Path] = None) -> Tuple[bool, str]:
        """返回 (allowed, reason)。monitor 模式下 reason 带 `monitor:` 前缀。"""
        if self.mode == "off":
            return True, ""
        reason = self._violation(argv, cwd, run_dir)
        if not reason:
            return True, ""
        if self.mode == "enforce":
            return False, reason
        return True, f"monitor: {reason}"


def check_command(argv: Sequence[str], *, cwd: Optional[Path] = None,
                  run_dir: Optional[Path] = None,
                  policy: Optional[CommandPolicy] = None) -> Tuple[bool, str]:
    return (policy or CommandPolicy.from_env()).check(argv, cwd=cwd, run_dir=run_dir)


_COMMAND_KEYS = ("command", "cmd", "argv", "shell_command", "shell", "exec")


def scan_tool_args(tool_name: str, args: Optional[Dict[str, Any]], *,
                   policy: Optional[CommandPolicy] = None,
                   cwd: Optional[Path] = None) -> Tuple[bool, str]:
    """从工具参数里找出命令形状的字段并检查。

    不是所有工具都有命令参数；没有就视为通过（不伪造拦截）。有的话按
    `shlex.split` 拆（字符串）或原样（列表）。
    """
    if not isinstance(args, dict):
        return True, ""
    pol = policy or CommandPolicy.from_env()
    for key, value in args.items():
        if key not in _COMMAND_KEYS:
            continue
        argv: List[str] = []
        if isinstance(value, str) and value.strip():
            try:
                argv = shlex.split(value, posix=(os.name != "nt"))
            except ValueError:
                argv = value.split()
        elif isinstance(value, (list, tuple)):
            argv = [str(v) for v in value]
        if not argv:
            continue
        ok, reason = pol.check(argv, cwd=cwd or Path(os.getcwd()))
        if not ok:
            return False, f"{tool_name}.{key}: {reason}"
        if reason:
            return True, f"{tool_name}.{key}: {reason}"
    return True, ""
