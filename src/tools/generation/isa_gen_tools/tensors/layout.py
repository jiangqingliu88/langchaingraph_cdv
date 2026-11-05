"""T1 布局 —— 形状 + dtype → 字节数 / 步长 / `rem_dim0`（§3.12.2）。

T1 在文档里的位置（§3.12.1 的五级转换）
    T1 逻辑坐标 → 张量内线性偏移   ← **本模块**
    T2 张量 → 物理存储位置          （address_service / allocator 的活）
    T3 分区地址 → 44bit 全局地址    （`domain/address.py`）
    T4 全局地址 → 指令字段          （`compile/annotate`）

    为什么 T1 到这里才实现：isa_gen 只**分配基地址**，从不碰张量内容，
    所以它不需要 T1。tensor_gen 要**按布局填数据**，才第一次需要它。

两个必须照抄文档的细节
    1. **dim0 按 256bit 原子打包**（§3.12.2）：

           cfg_dim0b_size = ceil(num_dim0 × elem_bits / 256)   -- 整块数
           cfg_dim0b_rem  =      (num_dim0 × elem_bits) % 256   -- 余数

       余数非零 = 最后一块没填满 —— 那**只有 BC 类指令能用**（`bc_only`），
       所以这里把 `rem_dim0` 一路带到 manifest 里（E4）。

    2. **步长以 256bit 行为单位**，字节偏移是 `(i2×s2 + i1×s1 + i0b) << 5`
       （`<<5` = ×32 字节）。所以 `stride_dim1` 是"dim0 方向占几行 256bit"，
       不是字节数 —— 混淆这两个会让所有非首行的数据错位。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Sequence, Tuple

#: dtype → 每元素位数。**只列 ISA 真的用到的**；未知 dtype 响亮失败，
#: 不猜一个位宽（猜错 = 整块数据错位，而且不报错）。
DTYPE_BITS: Dict[str, int] = {
    "fp32": 32, "fp16": 16, "bf16": 16, "int32": 32, "int16": 16, "int8": 8,
    "mxfp8": 8, "mxfp4": 4,
}

#: 256bit 原子 —— §3.12.2 T1 的打包粒度。
ATOM_BITS = 256
ATOM_BYTES = ATOM_BITS // 8          # 32


class LayoutError(ValueError):
    """布局算不出来（未知 dtype / 形状为空 / 维度太多）。"""


def dtype_bits(dtype: str) -> int:
    key = str(dtype or "").strip().lower()
    if key not in DTYPE_BITS:
        raise LayoutError(
            f"未知 dtype: {dtype!r}（已知：{sorted(DTYPE_BITS)}）"
        )
    return DTYPE_BITS[key]


@dataclass(frozen=True)
class Layout:
    """一个张量的 T1 布局。字段名与 manifest schema v1.1 对齐（§3.12.9）。"""

    shape: Tuple[int, ...]        # 原样（1..3 维）
    dims: Tuple[int, int, int]    # 归一化到 (dim2, dim1, dim0)
    dtype: str
    elem_bits: int

    dim0_blocks: int              # cfg_dim0b_size —— dim0 占几个 256bit 原子
    rem_dim0: int                 # cfg_dim0b_rem  —— 末块未填满的位数（0 = 整齐）
    stride_dim1: int              # 以 256bit 行为单位
    stride_dim2: int              # 同上
    n_bytes: int

    @property
    def bc_only(self) -> bool:
        """E4：`rem_dim0 != 0` 的张量只能被 BC 类指令引用。

        256bit 原子是普通 load/store 的搬运单位，末块不满就意味着
        "整块搬"会带上邻居的数据 —— 所以只有广播类（逐元素）能用。
        """
        return self.rem_dim0 != 0

    @property
    def n_elements(self) -> int:
        return self.dims[0] * self.dims[1] * self.dims[2]

    def to_manifest(self) -> Dict[str, object]:
        """manifest schema v1.1 的 `layout` 字段块。"""
        return {
            "shape": list(self.dims),          # [dim2, dim1, dim0]
            "stride_dim1": self.stride_dim1,
            "stride_dim2": self.stride_dim2,
            "rem_dim0": self.rem_dim0,
            "bc_only": self.bc_only,
        }


def normalize_shape(shape: Sequence[int]) -> Tuple[int, int, int]:
    """1..3 维 → `(dim2, dim1, dim0)`。低维补 1 在**高位**。

    `[64]` → `(1, 1, 64)`；`[64,128]` → `(1, 64, 128)`。
    补在高位是因为 dim0 是最内层（256bit 打包沿它走）—— 补在低位会把
    内层维度改掉，整块布局都跟着错。
    """
    dims = [int(d) for d in shape]
    if not dims:
        raise LayoutError("shape 为空")
    if len(dims) > 3:
        raise LayoutError(f"本 ISA 最多 3 维，拿到 {len(dims)} 维：{list(shape)}")
    if any(d <= 0 for d in dims):
        raise LayoutError(f"shape 含非正数：{list(shape)}")
    while len(dims) < 3:
        dims.insert(0, 1)
    return (dims[0], dims[1], dims[2])


def layout_of(shape: Sequence[int], dtype: str) -> Layout:
    """形状 + dtype → `Layout`。"""
    bits = dtype_bits(dtype)
    dim2, dim1, dim0 = normalize_shape(shape)

    dim0_bits = dim0 * bits
    blocks = math.ceil(dim0_bits / ATOM_BITS)
    rem = dim0_bits % ATOM_BITS

    stride_dim1 = blocks
    stride_dim2 = blocks * dim1
    n_bytes = stride_dim2 * dim2 * ATOM_BYTES

    return Layout(shape=tuple(int(d) for d in shape),
                  dims=(dim2, dim1, dim0), dtype=str(dtype).lower(),
                  elem_bits=bits, dim0_blocks=blocks, rem_dim0=rem,
                  stride_dim1=stride_dim1, stride_dim2=stride_dim2,
                  n_bytes=n_bytes)
