"""执行板块 —— 跑 EDA / 回归（不负责生成用例或判定签核）。"""
from __future__ import annotations

import importlib

PACKAGES = ("regression_tools",)


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.tools.execution.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
