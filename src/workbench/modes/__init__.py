"""SignOffAI 的两种工作模式（同一系统的不同意图）。

- Agent Mode：长循环理解、规划、生成、修复；可调用 Engine。
- Verify Mode：确定性编译/回归/覆盖率/证据/签核内核。

统一入口：`router.run(goal, mode=...)`；CLI `vagent work <goal>` 与
`vagent -p <goal> --mode agent|verify`。
按需导出工作模式，避免 API → agent_plane → modes 的反向初始化环。

公开入口与原 facade 一致：子模块照常 import，只有被使用时才加载其依赖。
"""

import importlib

_SUBMODULES = {"agent_mode", "verify_mode", "interaction", "router"}
_FUNCTIONS = {"run", "render", "exit_code"}


def __getattr__(name):
    if name in _SUBMODULES:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    if name in _FUNCTIONS:
        router = importlib.import_module(".router", __name__)
        value = getattr(router, name)
        globals()[name] = value
        return value
    raise AttributeError(name)


__all__ = ["agent_mode", "verify_mode", "run", "render", "exit_code"]
