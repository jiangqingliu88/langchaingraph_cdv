"""生成板块 —— 产生验证产物的工具。

按需加载（`from src.tools.generation import casemodel_tools`），避免导入
本包时把所有重依赖拉起来。
"""
from __future__ import annotations

import importlib

PACKAGES = ("casemodel_tools", "uvm_tools", "isa_gen_tools",
            "cmodel_tools", "scmodel_tools", "doc_tools")


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.tools.generation.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
