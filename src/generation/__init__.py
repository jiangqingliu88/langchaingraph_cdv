"""生成板块 —— 生成验证产物的工具（

case 模型引擎已删除；生成入口只剩 UVM / ISA IR / C 模型。"""
from __future__ import annotations

import importlib

from src.tools.boards import BOARDS

PACKAGES = BOARDS["generation"]


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.generation.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
