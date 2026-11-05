"""`encode` —— L3 二进制编码层（§3.1）：IR → `seq.hex` + `reg-init.txt`。

     from src.tools.generation.isa_gen_tools.encode import encode_ir, decode_word

     result = encode_ir(ir_dict, load_ops_registry())
     result.words        # [0x...] 32bit 指令字
     result.render_seq_hex()
     result.reg_init     # reg-init.txt 文本
     result.notes        # 做了但值得说一声的事

四件事分开放在四个文件，各自只有一件职责：

    word.py      32bit 指令字的位打包 / 解包（**接口约定**，与编码表无关）
    regalloc.py  IR 符号值 → 5bit 物理索引 + reg-init（§3.2.1 第 4 条）
    encoder.py   主流程：分配 → mask 装配 → 打包
    __init__.py  你在这里

**本层不 import langchain / ToolHub / Qt** —— 与 `isa_gen_tools` 全体同一条纪律。
"""
from __future__ import annotations

from .encoder import (GROUP_MASK_OP, RAW_CMD_OP, EncodedItem, EncodeError,
                      EncodeResult, decode_word, encode_ir)
from .regalloc import RegisterAllocator, parse_value, reg_name
from .word import (CUSTOM_0, CUSTOM_1, CUSTOM_2, CUSTOM_3, FAMILY_OPCODE,
                   FIELDS, WordError, describe, opcode_for_family,
                   parse_opcode, to_hex, unpack)

__all__ = [
    # 主流程
    "encode_ir", "decode_word", "EncodeResult", "EncodedItem", "EncodeError",
    "GROUP_MASK_OP", "RAW_CMD_OP",
    # 寄存器
    "RegisterAllocator", "parse_value", "reg_name",
    # 指令字
    "CUSTOM_0", "CUSTOM_1", "CUSTOM_2", "CUSTOM_3", "FAMILY_OPCODE", "FIELDS",
    "WordError", "describe", "opcode_for_family", "parse_opcode", "to_hex", "unpack",
]
