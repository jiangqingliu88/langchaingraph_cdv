"""环境产物生成器 —— `agents/`、`env/`、`bench/` 的统一入口。

第一批是**稳定门面**：内部仍调用 `tool_uvm.UVMGenerator`，但调用方
（verify / 测试 / 未来证据收集）只依赖这个模块，不直接依赖 3780 行的
`gen_uvm.py`。后续把 `UVMGenerator` 的解析/渲染拆进来时，门面签名不变。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Optional


def generate_env(inputs: Iterable[Path], output_root: Path,
                 renderer: Any = None) -> List[Path]:
    """按输入 YAML 生成 UVM 环境，返回生成的文件列表。"""
    from ...tool_uvm.gen_uvm import TEMPLATES_DIR, JinjaRenderer, UVMGenerator

    gen = UVMGenerator(renderer or JinjaRenderer(TEMPLATES_DIR),
                       output_root=Path(output_root))
    return gen.run([Path(p) for p in inputs])
