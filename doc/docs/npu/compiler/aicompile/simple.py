import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Tuple, Optional

# ------------------------------------------------------------
# 1. 核心类型与指令定义
# ------------------------------------------------------------

class CoreType(Enum):
    TENSOR = "tensor"
    VECTOR = "vector"

class OpCode(Enum):
    TENSOR_MATMUL = "tensor_matmul"
    VECTOR_BIAS_ADD = "vector_bias_add"
    VECTOR_RELU = "vector_relu"
    VECTOR_DOT = "vector_dot"
    SYNC = "sync"

@dataclass
class Descriptor:
    name: str
    bank_id: int
    offset: int
    shape: Tuple[int, int]
    stride: int
    layout: str

@dataclass
class Instruction:
    opcode: OpCode
    core: CoreType
    src_descs: List[Descriptor]
    dst_desc: Optional[Descriptor]
    extra: Dict[str, Any] = field(default_factory=dict)

# ------------------------------------------------------------
# 2. 异构编译器（容量已调大）
# ------------------------------------------------------------
class HeterogeneousCompiler:
    def __init__(self, num_banks: int = 8, bank_capacity: int = 10000):   # ← 修改这里
        self.num_banks = num_banks
        self.bank_capacity = bank_capacity
        self.banks = [np.zeros(bank_capacity, dtype=np.float32) for _ in range(num_banks)]
        self.descriptors: List[Descriptor] = []
        self.instructions: List[Instruction] = []
        self.next_bank_id = 0

    def _alloc_bank(self, data: np.ndarray) -> Descriptor:
        assert data.size <= self.bank_capacity, f"数据大小{data.size}超过Bank容量{self.bank_capacity}"
        bank_id = self.next_bank_id % self.num_banks
        self.next_bank_id += 1
        offset = 0
        self.banks[bank_id][offset:offset+data.size] = data.flatten()
        desc = Descriptor(
            name=f"data_{len(self.descriptors)}",
            bank_id=bank_id,
            offset=offset,
            shape=data.shape,
            stride=data.shape[1] if len(data.shape) >= 2 else data.shape[0],
            layout="tensor_block" if len(data.shape) >= 2 else "vector"
        )
        self.descriptors.append(desc)
        return desc

    def compile_linear_layer(self, weights: np.ndarray, bias: np.ndarray, 
                            input_vec: np.ndarray) -> List[Instruction]:
        instructions = []
        w_desc = self._alloc_bank(weights)
        inp_desc = self._alloc_bank(input_vec)
        b_desc = self._alloc_bank(bias)

        out_shape = (weights.shape[0], 1) if len(input_vec.shape)==1 else (weights.shape[0], input_vec.shape[1])
        out_desc = Descriptor(
            name="matmul_output", bank_id=0, offset=0,
            shape=out_shape, stride=out_shape[1], layout="tensor_block"
        )

        if weights.shape[1] >= 16 and weights.shape[0] >= 16:
            instr_matmul = Instruction(
                opcode=OpCode.TENSOR_MATMUL, core=CoreType.TENSOR,
                src_descs=[w_desc, inp_desc], dst_desc=out_desc,
                extra={"accumulate": False, "precision": "fp16"}
            )
            print(f"⚡ 调度到张量核心: {weights.shape} @ {input_vec.shape}")
        else:
            instr_matmul = Instruction(
                opcode=OpCode.VECTOR_DOT, core=CoreType.VECTOR,
                src_descs=[w_desc, inp_desc], dst_desc=out_desc,
                extra={"num_vectors": weights.shape[0]}
            )
            print(f"🧩 调度到矢量核心(点积): {weights.shape} @ {input_vec.shape}")
        instructions.append(instr_matmul)

        bias_out_desc = Descriptor(
            name="bias_add_output", bank_id=0, offset=0,
            shape=out_shape, stride=out_shape[1], layout="vector"
        )
        instr_bias = Instruction(
            opcode=OpCode.VECTOR_BIAS_ADD, core=CoreType.VECTOR,
            src_descs=[out_desc, b_desc], dst_desc=bias_out_desc,
            extra={"broadcast": True}
        )
        print(f"🧩 调度到矢量核心: 偏置加法")
        instructions.append(instr_bias)

        relu_out_desc = Descriptor(
            name="relu_output", bank_id=0, offset=0,
            shape=out_shape, stride=out_shape[1], layout="vector"
        )
        instr_relu = Instruction(
            opcode=OpCode.VECTOR_RELU, core=CoreType.VECTOR,
            src_descs=[bias_out_desc], dst_desc=relu_out_desc,
            extra={"threshold": 0.0}
        )
        print(f"🧩 调度到矢量核心: ReLU")
        instructions.append(instr_relu)

        instr_sync = Instruction(
            opcode=OpCode.SYNC, core=CoreType.TENSOR,
            src_descs=[], dst_desc=None,
            extra={"wait_for": "TENSOR"}
        )
        instructions.append(instr_sync)

        self.instructions.extend(instructions)
        return instructions

# ------------------------------------------------------------
# 3. 执行器
# ------------------------------------------------------------
class HeterogeneousExecutor:
    def __init__(self, compiler: HeterogeneousCompiler):
        self.compiler = compiler
        self.banks = compiler.banks

    def _read_data(self, desc: Descriptor) -> np.ndarray:
        # 处理任意维度的 shape
        total = 1
        for dim in desc.shape:
            total *= dim
        data = self.banks[desc.bank_id][desc.offset:desc.offset + total]
        return data.reshape(desc.shape)

    def run(self):
        print("\n🚀 执行异构指令流...")
        context = {}
        for instr in self.compiler.instructions:
            core_tag = f"[{instr.core.value.upper()}]" if instr.core else "[SYS]"
            if instr.opcode == OpCode.TENSOR_MATMUL:
                w = self._read_data(instr.src_descs[0])
                x = self._read_data(instr.src_descs[1])
                if len(x.shape) == 1: x = x.reshape(-1, 1)
                res = w @ x
                context["matmul_out"] = res
                print(f"{core_tag} 矩阵乘完成: {res.shape}")
            elif instr.opcode == OpCode.VECTOR_DOT:
                w = self._read_data(instr.src_descs[0])
                x = self._read_data(instr.src_descs[1])
                res = w @ x
                context["matmul_out"] = res.reshape(-1, 1)
                print(f"{core_tag} 点积完成: {res.shape}")
            elif instr.opcode == OpCode.VECTOR_BIAS_ADD:
                src = context.get("matmul_out")
                bias = self._read_data(instr.src_descs[1])
                if len(bias.shape) == 1: bias = bias.reshape(1, -1)
                res = src + bias
                context["bias_out"] = res
                print(f"{core_tag} 偏置加法完成: {res.shape}")
            elif instr.opcode == OpCode.VECTOR_RELU:
                src = context.get("bias_out")
                res = np.maximum(0, src)
                context["relu_out"] = res
                print(f"{core_tag} ReLU完成: {res.shape}")
            elif instr.opcode == OpCode.SYNC:
                print(f"⏳ 同步完成")
        final = context.get("relu_out")
        if final is not None:
            print(f"\n✅ 最终输出:\n{final.round(4)}")
        return context

# ------------------------------------------------------------
# 4. 主程序
# ------------------------------------------------------------
if __name__ == "__main__":
    # 显式指定容量足够大
    compiler = HeterogeneousCompiler(num_banks=8, bank_capacity=10000)
    
    weights = np.random.randn(64, 128).astype(np.float32)
    bias = np.random.randn(64).astype(np.float32)
    input_vec = np.random.randn(128).astype(np.float32)
    
    print("=" * 50)
    print(f"权重: {weights.shape}, 输入: {input_vec.shape}, 偏置: {bias.shape}")
    print("=" * 50)
    
    compiler.compile_linear_layer(weights, bias, input_vec)
    executor = HeterogeneousExecutor(compiler)
    executor.run()