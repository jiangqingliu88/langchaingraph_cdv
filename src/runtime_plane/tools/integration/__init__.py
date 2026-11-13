"""集成板块 —— 对外工具接口（IDE 桥等）。"""
from __future__ import annotations

import importlib

PACKAGES = ("ide_tools",)


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.runtime_plane.tools.integration.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
