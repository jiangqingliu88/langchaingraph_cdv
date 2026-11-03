"""环境产物生成器 —— `agents/`、`env/`、`bench/` 的统一入口。

调用方（verify / 测试 / 未来证据收集）只依赖这个模块，不直接依赖
`tool_uvm/gen_uvm.py`（它现在只是 CLI 入口）。实现在 `orchestrator.py`。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Optional


def generate_env(inputs: Iterable[Path], output_root: Path,
                 renderer: Any = None) -> List[Path]:
    """按输入 YAML 生成 UVM 环境，返回生成的文件列表。"""
    from ..constants import TEMPLATES_DIR
    from ..render.jinja_renderer import JinjaRenderer
    from .orchestrator import UVMGenerator

    gen = UVMGenerator(renderer or JinjaRenderer(TEMPLATES_DIR),
                       output_root=Path(output_root))
    return gen.run([Path(p) for p in inputs])
