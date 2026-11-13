"""人读视图板块 —— 把人维护的文档/表格编译成机器可执行的契约。

按需加载（`from src.runtime_plane.tools.humanview import aivm_ir`），避免导入本包时把
openpyxl 这类依赖拉起来。
"""
from __future__ import annotations

import importlib

from src.runtime_plane.tools.boards import BOARDS

PACKAGES = BOARDS["humanview"]


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.runtime_plane.tools.humanview.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
