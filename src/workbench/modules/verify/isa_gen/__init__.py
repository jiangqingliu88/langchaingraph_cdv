"""ISA 激励模块。

输入一份 `.ir.txt`（手写 IR 或已解析 seq.ir），经 `isa_ir_tools` 的三阶段
流水线生成 seq.ir 与 commands.tsv；界面只经 bridge 白名单访问工具。
"""
from .module import IsaGenModule

__all__ = ["IsaGenModule"]
