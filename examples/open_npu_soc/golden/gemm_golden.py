"""Open NPU SoC v0.1 的 INT8 GEMM 黄金模型 / 向量生成器。

生成三份 `$readmemh` 文件供 `tb_soc_top.sv` 读取：

    vectors/a.hex    A[M][K]  INT8（两位十六进制，二补码）
    vectors/b.hex    B[K][N]  INT8
    vectors/c.hex    C[M][N]  INT32（八位十六进制，二补码）

默认 8x8x8，固定 seed —— **同一份输入每次生成同一组向量**，这是证据可复现
的前提。v0.1 先证明「CPU/NICE → DMA → SRAM → GEMM → IRQ → 比较」这条链，
后续再扩数据类型/矩阵尺寸。

用法：
    python examples/open_npu_soc/golden/gemm_golden.py --out examples/open_npu_soc/vectors
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def _int8(value: int) -> int:
    value &= 0xFF
    return value - 0x100 if value >= 0x80 else value


def generate(size: int = 8, seed: int = 20261031) -> dict:
    rng = random.Random(seed)
    a = [[rng.randint(-8, 7) for _ in range(size)] for _ in range(size)]
    b = [[rng.randint(-8, 7) for _ in range(size)] for _ in range(size)]
    c = [[sum(a[i][k] * b[k][j] for k in range(size))
          for j in range(size)] for i in range(size)]
    return {"size": size, "seed": seed, "a": a, "b": b, "c": c}


def write_vectors(doc: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    size = doc["size"]
    a = [v for row in doc["a"] for v in row]
    b = [v for row in doc["b"] for v in row]
    c = [v for row in doc["c"] for v in row]
    (out_dir / "a.hex").write_text(
        "\n".join(f"{_int8(v) & 0xFF:02x}" for v in a) + "\n", encoding="utf-8")
    (out_dir / "b.hex").write_text(
        "\n".join(f"{_int8(v) & 0xFF:02x}" for v in b) + "\n", encoding="utf-8")
    (out_dir / "c.hex").write_text(
        "\n".join(f"{v & 0xFFFFFFFF:08x}" for v in c) + "\n", encoding="utf-8")
    meta = {"size": size, "seed": doc["seed"],
            "shape": {"M": size, "N": size, "K": size},
            "dtype": {"a": "int8", "b": "int8", "c": "int32"}}
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Open NPU SoC INT8 GEMM golden vectors")
    parser.add_argument("--out", default="vectors", help="输出目录")
    parser.add_argument("--size", type=int, default=8, help="M=N=K（默认 8）")
    parser.add_argument("--seed", type=int, default=20261031, help="确定性种子")
    args = parser.parse_args(argv)
    doc = generate(size=args.size, seed=args.seed)
    meta = write_vectors(doc, Path(args.out))
    print(f"[golden] {meta['shape']} dtype={meta['dtype']} -> {Path(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
