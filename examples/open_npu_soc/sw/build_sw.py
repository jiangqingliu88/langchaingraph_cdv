"""编译 E203 bare-metal 固件（不依赖 make）。

Windows 环境经常没有 make；这个脚本读取 `../toolchain/prefix.mk`，调用
`riscv64-unknown-elf-gcc` / objcopy / objdump，产出 `gemm_8x8.elf/.hex/.dump`。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREFIX_MK = HERE.parent / "toolchain" / "prefix.mk"


def _prefix() -> str:
    if PREFIX_MK.is_file():
        text = PREFIX_MK.read_text(encoding="utf-8")
        m = re.search(r"^RISCV_PREFIX\s*\?=\s*(.+)$", text, re.M)
        if m:
            return m.group(1).strip()
    return os.environ.get("RISCV_PREFIX", "riscv64-unknown-elf-")


def _run(argv) -> None:
    print("+", " ".join(str(x) for x in argv))
    subprocess.run([str(x) for x in argv], cwd=str(HERE), check=True)


def main() -> int:
    prefix = _prefix()
    cc = Path(prefix + "gcc.exe")
    if not cc.is_file():
        print(f"找不到 {cc}\n先运行 python ../toolchain/setup_toolchain.py", file=sys.stderr)
        return 2
    arch = ["-march=rv32imafdc", "-mabi=ilp32f"]
    _run([cc, *arch, "-nostdlib", "-nostartfiles", "-ffreestanding", "-O2",
          "-I.", "-T", "e203.ld", "startup/startup.S", "tests/gemm_8x8.c",
          "-o", "gemm_8x8.elf"])
    _run([prefix + "objcopy.exe", "-O", "verilog", "gemm_8x8.elf", "gemm_8x8.hex"])
    with (HERE / "gemm_8x8.dump").open("w", encoding="utf-8") as fh:
        print("+", prefix + "objdump.exe -d gemm_8x8.elf > gemm_8x8.dump")
        subprocess.run([prefix + "objdump.exe", "-d", "gemm_8x8.elf"],
                       cwd=str(HERE), stdout=fh, check=True)
    # E203 tb_top.v 读的是 `<TESTCASE>.verilog`（$readmemh，8-bit 行）
    (HERE / "gemm_8x8.verilog").write_bytes((HERE / "gemm_8x8.hex").read_bytes())
    print("built gemm_8x8.elf / .hex / .verilog / .dump")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
