"""流程板块 —— 签核 / 血缘 / 趋势等跨阶段能力。"""
from __future__ import annotations

import importlib

PACKAGES = ("flow_tools", "trend_tools")


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.tools.flow.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
