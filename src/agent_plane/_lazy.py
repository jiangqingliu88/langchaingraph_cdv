"""Agent 子包 `__init__` 的惰性导出工具（PEP 562）。

为什么需要：Domain 包里既有不依赖 SDK 的生成器/工具（`main.py`、`tools.py`、
`graph.py`），也有依赖 `openai-agents` 的 `agent.py`。若 `__init__.py` 在
import 时就把 `.agent` 拉起来，只想要生成器的 CLI/测试也会被 SDK 缺失挡住。
用惰性 `__getattr__` 后，`from ...formal_agent import generate_formal_plan`
只加载 `main`，`from ...formal_agent import FormalAgent` 才加载 `agent`。
"""
from __future__ import annotations

from importlib import import_module
from typing import Any, Callable, Dict, Tuple


def make_getattr(module_globals: Dict[str, Any],
                 mapping: Dict[str, Tuple[str, str]],
                 module_name: str) -> Callable[[str], Any]:
    def __getattr__(name: str) -> Any:
        target = mapping.get(name)
        if target is None:
            raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
        package, attr = target
        value = getattr(import_module(package), attr)
        module_globals[name] = value
        return value

    return __getattr__


__all__ = ["make_getattr"]
