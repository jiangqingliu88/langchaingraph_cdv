"""下载/解压 Nuclei RISC-V GNU 工具链，并生成 `prefix.mk`。

为什么不是 xPack：GitHub Release 的 300MB 包在本机网络上只有 ~20KB/s，
实际会看起来"卡死"。Nuclei 官方镜像（download.nucleisys.com）走的是国内
CDN，实测 MB/s 级；E203 本身也默认 `riscv-nuclei-elf-` 前缀，语义更一致。

用法：
    python examples/open_npu_soc/toolchain/setup_toolchain.py
    python examples/open_npu_soc/toolchain/setup_toolchain.py --no-download

生成：
    toolchain/<解压目录>/bin/riscv-nuclei-elf-gcc.exe
    toolchain/prefix.mk          # RISCV_PREFIX ?= <abs>/bin/riscv-nuclei-elf-
"""
from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = ("https://download.nucleisys.com/upload/files/toolchain/gcc/"
       "nuclei_riscv_newlibc_prebuilt_win32_2024.06.zip")
EXPECTED = 1_032_921_203


def _download(target: Path) -> None:
    print(f"[toolchain] 下载 {URL}")
    print(f"[toolchain] 目标 {target}（约 {EXPECTED / 1e9:.2f} GB）")
    tmp = target.with_suffix(".zip.part")
    with urllib.request.urlopen(URL) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 / total
                print(f"\r[toolchain] {done/1e6:7.1f}/{total/1e6:.1f} MB "
                      f"({pct:5.1f}%)", end="", flush=True)
    print()
    tmp.replace(target)


def _find_bin(root: Path) -> tuple[Path, str] | None:
    for gcc in sorted(root.rglob("riscv*-gcc.exe")):
        name = gcc.name[:-4]  # strip .exe
        if name.endswith("-gcc"):
            return gcc.parent, name[: -len("gcc")]
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Setup Nuclei RISC-V toolchain")
    parser.add_argument("--no-download", action="store_true",
                        help="只用已存在的 zip")
    parser.add_argument("--force", action="store_true", help="重新下载")
    args = parser.parse_args(argv)

    here = Path(__file__).resolve().parent
    archive = here / "nuclei-gcc.zip"
    if args.force and archive.exists():
        archive.unlink()
    if not archive.exists():
        if args.no_download:
            print(f"[toolchain] 缺少 {archive}", file=sys.stderr)
            return 2
        _download(archive)
    if archive.stat().st_size != EXPECTED:
        print(f"[toolchain] 包大小不符：{archive.stat().st_size} != {EXPECTED}"
              "（可能下载未完成；加 --force 重下）", file=sys.stderr)
        return 2

    print(f"[toolchain] 解压 {archive.name} …")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(here)

    found = _find_bin(here)
    if found is None:
        print("[toolchain] 解压后找不到 riscv*-gcc.exe", file=sys.stderr)
        return 2
    bin_dir, prefix_name = found
    prefix = bin_dir / prefix_name
    (here / "prefix.mk").write_text(
        f"RISCV_PREFIX ?= {prefix.as_posix()}\n", encoding="utf-8")
    print(f"[toolchain] 编译器：{prefix}gcc")
    print(f"[toolchain] 已写 {here / 'prefix.mk'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
