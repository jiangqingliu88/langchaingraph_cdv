"""生成板块 —— 产生验证产物的工具（

casemodel_tools 已迁到 `src.layers.l3_decision.casemodel`，不再在此列。
"""
from __future__ import annotations

import importlib

PACKAGES = ("uvm_tools", "isa_gen_tools", "cmodel_tools", "scmodel_tools")


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.tools.generation.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
