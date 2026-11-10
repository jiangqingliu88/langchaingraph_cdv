"""生成板块 —— 产生验证产物的工具（

case 模型引擎已删除；生成入口只剩 UVM / ISA IR / C 模型 / SC 模型。
"""
from __future__ import annotations

import importlib

#: 与 `src.tools.boards.BOARDS["generation"]` 保持一致。这里**不 import
#: boards**：工具包的分层测试会 `import ...generation.<tool>.domain`，
#: 包 `generation` 的 `__init__` 一旦 eager import `src.tools.boards`，
#: 就会被判成"工具之间 import"（跨工具约束）。懒加载即可。
PACKAGES = (
    "uvm_tools", "isa_ir_tools", "cmodel_tools", "scmodel_tools", "doc_tools",
)


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.tools.generation.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
