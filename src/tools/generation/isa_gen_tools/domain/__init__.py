"""领域层 —— ISA 事务生成器的数据与不变式。

分层规则（整个包内唯一需要记住的规则）
    domain      不 import 本包其它任何层
    repository  只 import domain
    compile     import domain（+ repository 的产物）
    analysis    import domain（+ repository 的产物）

    理由与 `vplan/runtime/domain` 同一套：依赖方向是**靠 import 纪律维持的**，
    没有别的机制保证它。一个层悄悄往上 import 一次，分层就名存实亡了。

这一层是**不变量住的地方**，不是数据结构集合
    四条结构性不变式各有归属：

    · 随机化的最小单元是事务（§3.9）      → `transaction.Transaction`
    · 标量走字段、张量走内存（§3.14.1）    → `instruction.IrInstruction.__post_init__`
    · 编译期失败是一等公民（§3.0.1）       → `errors.CompileError` 的十个具名子类
    · 确定性（§3.12.9 E5）                → 不在这一层，在 `compile/sequencer.py`

    换一句话说：**这里没有"生成"逻辑**。domain 只回答"什么是一条合法的事务 / 指令 /
    地址"，不回答"下一条该生成什么"。
"""
from .address import (ADDR_BITS, FIELD_BITS, FIELD_SHIFTS, OFFSET_BITS, GlobalAddr,
                      McastMode, MemFlag)
from .errors import (COMPILE_ERROR_KINDS, AllocError, CompileError, DataPathError,
                     DeterminismError, IsaGenError, LintError,
                     OperandUnsupportedError, PairingError, RegistryError,
                     SchemaError, SolverError, UnresolvedRefError, WhitelistError)
from .instruction import IR_KEYS, Flags, IrInstruction, Operands
from .opcode import (Collision, IsaFamily, MaskSemantics, OpClass, OpRegistry,
                     OpRole, OpSpec, PairingKind, format_funct7, parse_flags,
                     parse_funct7)
from .operands import (ADDR_PART_NAMES, ROLE_ALIASES, OperandSpec, parse_operand,
                       parse_operands)
from .program import IrProgram
from .transaction import (Effect, HardConstraint, Pairing, PreStep, Transaction,
                          TransactionRegistry, TxnSpec, build_transaction)

__all__ = [
    # address
    "GlobalAddr", "MemFlag", "McastMode", "ADDR_BITS", "OFFSET_BITS",
    "FIELD_BITS", "FIELD_SHIFTS",
    # errors
    "IsaGenError", "CompileError", "COMPILE_ERROR_KINDS", "SchemaError",
    "RegistryError", "LintError", "UnresolvedRefError", "AllocError",
    "SolverError", "WhitelistError", "PairingError", "DataPathError",
    "DeterminismError", "OperandUnsupportedError",
    # instruction
    "Flags", "Operands", "IrInstruction", "IR_KEYS",
    # opcode
    "OpClass", "OpRole", "OpSpec", "OpRegistry", "IsaFamily", "MaskSemantics",
    "PairingKind", "Collision", "parse_funct7", "format_funct7", "parse_flags",
    # operands
    "OperandSpec", "parse_operand", "parse_operands", "ROLE_ALIASES",
    "ADDR_PART_NAMES",
    # transaction
    "Transaction", "Pairing", "PreStep", "HardConstraint", "Effect",
    "build_transaction", "TxnSpec", "TransactionRegistry",
    # program
    "IrProgram",
]
