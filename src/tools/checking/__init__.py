"""检查板块 —— 只读/判定类工具（断言、debug、覆盖率分析、spec 校验）。

verification_os 已迁到 `src.layers.l3_decision.contract`，不再在此列。
"""
from __future__ import annotations

import importlib

PACKAGES = ("assertion_tools",)


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.tools.checking.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
