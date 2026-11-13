"""SignOffAI 的两种工作模式（同一系统的不同意图）。

- Agent Mode：长循环理解、规划、生成、修复；可调用 Engine。
- Verify Mode：确定性编译/回归/覆盖率/证据/签核内核。

统一入口：`router.run(goal, mode=...)`；CLI `vagent work <goal>` 与
`vagent -p <goal> --mode agent|verify`。
"""
from . import agent_mode, verify_mode
from .router import exit_code, render, run

__all__ = ["agent_mode", "verify_mode", "run", "render", "exit_code"]
