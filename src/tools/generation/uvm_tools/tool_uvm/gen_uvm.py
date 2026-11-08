#!/usr/bin/env python3
"""gen_uvm.py —— UVM 生成的命令行入口（**只剩入口**）。

实现都在 `uvm_tools/generation/`；旧调用方已迁到 `generation.*` 导入，
这里不再做名字 re-export。两种入口照旧：

    python gen_uvm.py -i <yaml_dir> -o <output_dir>
    python -m src.tools.generation.uvm_tools.tool_uvm.gen_uvm -i ... -o ...
"""
from __future__ import annotations

import sys
from pathlib import Path

try:  # 包内导入（python -m 路径）
    from ..tool_uvm.generators.cli import main
except ImportError:  # 直接脚本执行（python gen_uvm.py）—— 没有父包
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from generation.generators.cli import main  # type: ignore[no-redef]


if __name__ == "__main__":
    raise SystemExit(main())
