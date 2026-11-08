"""执行板块 —— 跑 EDA / 回归的工具。

真实的回归实现已迁到 `src/layers/l2_orchestration/regression_tools`；
这里保留板块入口，按需加载仍在 `src/tools/execution/` 下的包。
"""
from __future__ import annotations

import importlib

from src.tools.boards import BOARDS

PACKAGES = BOARDS["execution"]


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.tools.execution.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
