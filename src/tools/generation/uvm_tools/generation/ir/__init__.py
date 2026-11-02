"""UVM IR —— 生成器迁移的落点。

当前 `gen_uvm.py` 仍直接解析 spec/YAML 并渲染。这里先定义**统一中间表示**
（agent / env / test / sequence / connection）与校验器，作为后续把
parsing → IR → render 拆开的契约；新代码优先读写 IR，不再各自理解 spec。
"""
from src.tools.generation.uvm_tools.generation.ir.uvm_ir import (
    UVMAgentIR, UVMConnectionIR, UVMEnvIR, UVMIR, UVMSequenceIR, UVMTestIR,
    build_agent_ir, build_uvm_ir, validate_agent_ir, validate_ir,
)

__all__ = [
    "UVMAgentIR", "UVMConnectionIR", "UVMEnvIR", "UVMIR", "UVMSequenceIR",
    "UVMTestIR", "build_agent_ir", "build_uvm_ir", "validate_agent_ir",
    "validate_ir",
]
