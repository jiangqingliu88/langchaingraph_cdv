"""张量取值 —— 模式库 + dtype 打包 + **指数安全域**（§3.12.9 的 E1）。

模式库（文档 §3.12.9 提到的四类）
    `gauss`     高斯 —— 最常见，`exp_range` 用来防溢出
    `lattice`   规则格 —— **默认**。取可精确表示的小整数，先让链路跑通，
                比"随便来点随机数"更容易看出数据错位
    `saturate`  饱和角 —— 顶到 exp_range 的两端，专门压边界
    `zero`      全零 —— 后续覆盖写测试的干净底

指数安全域（E1）是**硬约束**
    「超限自动缩放并重生成，并在 manifest 留痕」——所以本模块**不是**简单 clamp：
    超限的值按指数差整体缩放（保住有效数字），并且**逐张量记下有没有缩放**，
    由 manifest 的 `exp_range.scaled` 带出去。

    为什么不能只 clamp：clamp 会把一堆值压到同一个边界值上，
    仿真的期望值分布就跟生成时想造的不是一回事了 —— 而且不报错。

dtype 打包
    `fp32` / `fp16` 走 `struct`（分别是 `<f` / `<e`）。
    `bf16` **不自己算** —— 它是 fp32 截掉低 16 位（truncate，不是 round），
    独立实现一遍迟早和硬件的舍入方式对不上。所以先打 fp32 再砍尾巴。
"""
from __future__ import annotations

import math
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .layout import Layout, LayoutError

#: 支持的模式。**未知模式响亮失败** —— 落回默认会让人以为"我写的高斯生效了"。
PATTERNS = ("gauss", "lattice", "saturate", "zero")

DEFAULT_PATTERN = "lattice"


class ValueError_(ValueError):
    """取值生成失败（未知模式 / dtype 打不了包）。"""


# ── 取值 ─────────────────────────────────────────────────────

def make_values(layout: Layout, *, pattern: str, draw: Any,
                exp_range: Optional[Sequence[float]] = None) -> Tuple[List[float], bool]:
    """按模式造 `n_elements` 个值。返回 `(values, scaled)`。

    `scaled` = 有没有为了满足 `exp_range` 缩放过 —— 要带进 manifest（E1 留痕）。
    """
    name = (pattern or DEFAULT_PATTERN).strip().lower()
    if name not in PATTERNS:
        raise ValueError_(
            f"未知 pattern: {pattern!r}（已知：{list(PATTERNS)}）"
        )

    n = layout.n_elements
    lo, hi = _exp_bounds(exp_range)
    scaled = False

    if name == "zero":
        return [0.0] * n, False

    raw: List[float] = []
    if name == "lattice":
        # 可精确表示的小整数来回走 —— 走不通链路时一眼能看出错位
        for i in range(n):
            raw.append(float((i % 17) - 8))
    elif name == "gauss":
        for _ in range(n):
            # Box-Muller：只要 [0,1) 的均匀数，`Draw` 没有 float 接口，
            # 所以用整数拼一个 53bit 的尾数（够双精度用）
            u1 = (_int53(draw) + 1) / (1 << 53)
            u2 = _int53(draw) / (1 << 53)
            raw.append(math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2))
    else:  # saturate
        for i in range(n):
            sign = 1.0 if (i % 2 == 0) else -1.0
            raw.append(sign * (2.0 ** hi if hi else 1.0))

    values: List[float] = []
    for x in raw:
        y = _fit_exp(x, lo, hi)
        if y != x:
            scaled = True
        values.append(y)
    return values, scaled


def _int53(draw: Any) -> int:
    """从 `Draw` 里取 53 个随机 bit（拼双精度尾数用）。"""
    acc = 0
    for _ in range(53):
        acc = (acc << 1) | (1 if draw.chance(0.5) else 0)
    return acc


def _exp_bounds(exp_range: Optional[Sequence[float]]) -> Tuple[Optional[int], Optional[int]]:
    """`[-6, 6]` → `(-6, 6)`。没给就是 `(None, None)` = 不限。"""
    if not exp_range:
        return None, None
    lo, hi = int(math.floor(float(exp_range[0]))), int(math.ceil(float(exp_range[1])))
    return lo, hi


def _fit_exp(x: float, lo: Optional[int], hi: Optional[int]) -> float:
    """把 `x` 的二进制指数压回 `[lo, hi]`。**缩放而非截断** —— 见模块头。"""
    if x == 0.0 or (lo is None and hi is None):
        return x
    e = math.floor(math.log2(abs(x)))
    target = e
    if hi is not None and e > hi:
        target = hi
    elif lo is not None and e < lo:
        target = lo
    if target == e:
        return x
    return math.copysign(abs(x) * (2.0 ** (target - e)), x)


# ── dtype 打包 ────────────────────────────────────────────────

def pack_values(values: Sequence[float], dtype: str) -> bytes:
    """值序列 → 小端字节。每元素按 dtype 的位宽紧挨着排。"""
    key = str(dtype or "").strip().lower()
    if key == "fp32":
        return b"".join(struct.pack("<f", float(v)) for v in values)
    if key == "fp16":
        return b"".join(struct.pack("<e", float(v)) for v in values)
    if key == "bf16":
        # bf16 = fp32 的高 16 位（truncate）。低 16 位直接丢 —— 见模块头。
        out = bytearray()
        for v in values:
            out += struct.pack("<f", float(v))[2:4]
        return bytes(out)
    if key in ("int32", "int16", "int8"):
        fmt = {"int32": "<i", "int16": "<h", "int8": "<b"}[key]
        return b"".join(struct.pack(fmt, int(v)) for v in values)
    raise ValueError_(f"dtype {dtype!r} 还不能打包（mxfp4/mxfp8 要先压指数位，"
                      f"见 §3.12.9 E1）")


def to_hex_lines(data: bytes) -> str:
    """字节 → `tensors/*.hex` 文本。**每行一个 32bit 字，8 位大写 hex**。

    为什么不按元素宽度分行：SPAD 的搬运粒度是 32bit，按 32bit 分行之后，
    "第几行" = "第几个 SPAD 字"，对不上时一眼能数出来。末行不足 4 字节补零。
    """
    padded = data + b"\x00" * ((-len(data)) % 4)
    lines = []
    for i in range(0, len(padded), 4):
        word = int.from_bytes(padded[i:i + 4], "little")
        lines.append(f"{word:08X}")
    return "".join(line + "\n" for line in lines)


def content_hash(data: bytes) -> str:
    """数据哈希 —— E7 的内容寻址缓存键（也是 manifest 的 `content_hash`）。"""
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]
