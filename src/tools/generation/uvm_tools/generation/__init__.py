"""生成层 —— constants / parsing / models / render / ir / generators。

`tool_uvm/gen_uvm.py` 只剩 CLI 入口（不再 re-export），实现全部在这几层里；
新代码直接从这里导入，不要再往 `tool_uvm/` 里加逻辑。
"""
from . import constants, generators, ir, models, parsing, render  # noqa: F401

__all__ = ["constants", "models", "parsing", "render", "ir", "generators"]
