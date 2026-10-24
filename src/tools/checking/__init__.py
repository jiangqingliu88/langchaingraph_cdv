"""检查板块 —— 只读/判定类工具（断言、debug、覆盖率分析、spec 校验）。"""
from __future__ import annotations

import importlib

PACKAGES = ("assertion_tools", "debug_tools", "coverage_tools", "spec_tools")


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.tools.checking.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
