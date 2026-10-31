"""命令适配 —— 把「工具名 + 参数」翻译成平台可执行的 argv。

只做**最小**适配：Windows 上 `foo.sh` 用 bash 跑；其余原样透传。真实 EDA
参数仍由 `regression_tools/backend_profiles.py` 生成，这里不重复那一套。
"""
from __future__ import annotations

import os
from typing import List, Protocol


class CommandAdapter(Protocol):
    def wrap(self, argv: List[str], cwd: str) -> List[str]: ...


class PassthroughAdapter:
    def wrap(self, argv: List[str], cwd: str) -> List[str]:
        return list(argv)


class BashScriptAdapter:
    """`sim.sh` → `bash sim.sh`；已经是 bash/sh 就原样。"""

    def wrap(self, argv: List[str], cwd: str) -> List[str]:
        if not argv:
            return []
        head = str(argv[0]).lower()
        if head.endswith((".sh", ".bash")) and os.name == "nt":
            return ["bash", *argv]
        return list(argv)


_PASSTHROUGH = PassthroughAdapter()
_BASH = BashScriptAdapter()
DEFAULT_TOOL_ADAPTERS = {"bash": _PASSTHROUGH, "sh": _PASSTHROUGH}


def adapter_for(tool: str) -> CommandAdapter:
    name = os.path.basename(str(tool)).lower()
    if name.endswith((".sh", ".bash")):
        return _BASH
    return DEFAULT_TOOL_ADAPTERS.get(name, _PASSTHROUGH)


def adapt(argv: List[str], cwd: str = "") -> List[str]:
    if not argv:
        return []
    return adapter_for(argv[0]).wrap(list(argv), cwd)
