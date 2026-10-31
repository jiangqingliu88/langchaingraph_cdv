"""把 Open NPU 作为 E203 NICE co-processor 接入（M1 patch）。

做两件事：
  1. 把 `rtl/cpu/e203_nice_npu_adapter.sv` 复制为
     `e203_hbirdv2/rtl/e203/subsys/e203_nice_npu_adapter.v`
     （E203 vsim 的 wildcard 只收 rtl/e203/**/*.v）；
  2. 把 `e203_cpu.v` 里的 `e203_subsys_nice_core` 实例换成我们的适配器。

可重复执行；`--revert` 换回 E203 自带示例 core。
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # examples/open_npu_soc
E203 = ROOT / "e203_hbirdv2"
CPU = E203 / "rtl/e203/core/e203_cpu.v"
ADAPTER_DST = E203 / "rtl/e203/subsys/e203_nice_npu_adapter.v"
GEMM_DST = E203 / "rtl/e203/npu/int8_gemm.v"
ORIG = "e203_subsys_nice_core u_e203_nice_core"
OURS = "e203_nice_npu_adapter  u_e203_nice_core"


def _replace(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise SystemExit(f"{path}: 找不到 NICE 实例化 {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revert", action="store_true")
    args = parser.parse_args(argv)

    if args.revert:
        changed = _replace(CPU, OURS, ORIG)
        print("reverted" if changed else "already original")
        return 0

    shutil.copy2(ROOT / "rtl/cpu/e203_nice_npu_adapter.sv", ADAPTER_DST)
    GEMM_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "rtl/npu/int8_gemm.sv", GEMM_DST)
    changed = _replace(CPU, ORIG, OURS)
    print("patched" if changed else "already patched")
    print(f"  {ADAPTER_DST}")
    print(f"  {GEMM_DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
