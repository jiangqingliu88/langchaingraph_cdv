"""isa_gen_tools —— NPU ISA 事务序列生成器（HM057）。

干什么
    吃一份**场景 DSL**（YAML：意图 / 资源 / 事务池 / 形状与精度 / 编排），
    吐一份 **IR**（ISA 事务层 JSON：带语义标注的指令流 + 地址分配 + 张量引用）。
    对应 `08_验证策略.md` §3.5 那条流水线的生成侧前两段：

        DSL(YAML) ──求解器──► IR(JSON) ──编码器──► 32bit(seq.hex, v1)

    编码器**不在本包**：IR 是文档反复引用的单一契约层（TB 执行器消费 IR、
    比对模块靠 IR 的 `binds/writes` 索引），先把这一层钉死。

四条结构性不变式（详见 `domain/` 各模块头）
    1. 随机化的最小单元是**事务**，不是指令 —— `domain/transaction.py`
    2. 标量走指令字段、张量走内存，两条通路不交叉 —— `domain/instruction.py`
    3. 编译期失败是一等公民 —— `domain/errors.py`
    4. 确定性：加一个张量不动既有比特（E5）—— `compile/sequencer.py`

与别的工具的关系
    **没有 import 关系。** 与 tensor_gen 之间是文件契约（`preload.json` 里的
    `ref` 句柄），与 `tool_uvm` 之间是文件契约（IR 不产 UVM 代码）。

用法
    python -m src.tools.isa_gen_tools.cli compile <dsl.yaml> -o out/
    from src.tools.isa_gen_tools.api import run_compile
"""
from __future__ import annotations

from .api import (RUNNERS, TOOL_COMPILE, TOOL_EXPLAIN, TOOL_NAMES, TOOL_OPS,
                  TOOL_VALIDATE, run_compile, run_explain, run_ops, run_validate)

__version__ = "0.1"

__all__ = [
    "__version__",
    "run_validate", "run_compile", "run_explain", "run_ops",
    "TOOL_VALIDATE", "TOOL_COMPILE", "TOOL_EXPLAIN", "TOOL_OPS",
    "TOOL_NAMES", "RUNNERS",
]
