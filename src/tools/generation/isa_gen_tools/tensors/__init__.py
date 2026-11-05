"""`tensors` —— tensor_gen：`preload.json` 的句柄 → **真的张量数据**（§3.12.9）。

     from src.tools.generation.isa_gen_tools.tensors import build_tensors

     bundle = build_tensors(out["preload"], out["case"])
     bundle.entries[0].hex_text      # 写进 tensors/<name>.hex
     bundle.entries[0].manifest      # 写进 manifest/<name>.json
     bundle.registry                 # 写进 registry.json

四件事分开放：

    layout.py      T1 布局（形状+dtype → 字节数/步长/rem_dim0，§3.12.2）
    values.py      模式库 + dtype 打包 + **指数安全域**（E1）
    generator.py   主流程：每个对象一条派生流（E5）→ 数据 + manifest v1.1
    __init__.py    你在这里

**本层不 import langchain / ToolHub / Qt** —— 与 `isa_gen_tools` 全体同一条纪律。
"""
from __future__ import annotations

from .generator import TensorBundle, TensorEntry, build_tensors
from .layout import (ATOM_BITS, ATOM_BYTES, DTYPE_BITS, Layout, LayoutError,
                     dtype_bits, layout_of, normalize_shape)
from .values import (DEFAULT_PATTERN, PATTERNS, content_hash, make_values,
                     pack_values, to_hex_lines)

__all__ = [
    # 主流程
    "build_tensors", "TensorBundle", "TensorEntry",
    # T1 布局
    "layout_of", "Layout", "LayoutError", "DTYPE_BITS", "dtype_bits",
    "normalize_shape", "ATOM_BITS", "ATOM_BYTES",
    # 取值
    "make_values", "pack_values", "to_hex_lines", "content_hash",
    "PATTERNS", "DEFAULT_PATTERN",
]
