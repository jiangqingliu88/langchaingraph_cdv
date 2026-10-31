# RISC-V 工具链

E203 默认使用 `riscv-nuclei-elf-` 前缀的 GNU 工具链。本目录提供：

- `setup_toolchain.py`：从 Nuclei 官方镜像下载/解压，并生成 `prefix.mk`。
- `prefix.mk`：`RISCV_PREFIX ?= <toolchain>/bin/riscv-nuclei-elf-`（生成物，不进 git）。

## 为什么不用 GitHub 上的 xPack 包

xPack 的 Windows 包约 300–465MB，本机实测从 GitHub Release 下载只有
~20KB/s，看起来就像"卡死"。Nuclei 的 `download.nucleisys.com` 镜像实测
MB/s 级，且前缀与 E203 的 Makefile 默认值一致。

## 安装

```bash
python examples/open_npu_soc/toolchain/setup_toolchain.py
```

如果包已下载：

```bash
python examples/open_npu_soc/toolchain/setup_toolchain.py --no-download
```

然后验证：

```bash
source examples/open_npu_soc/toolchain/env.sh 2>/dev/null || true
# 或直接用 prefix.mk 里的路径：
examples/open_npu_soc/toolchain/**/bin/riscv-nuclei-elf-gcc --version
```

## E203 自带测试

`e203_hbirdv2/riscv-tools/riscv-tests/isa/generated/` 里已经带了预编译的
`.elf/.verilog`，所以 **E203 自测不依赖本工具链**；工具链用于编译我们自己的
C 程序 / bare-metal 固件。

## 编译自定义固件

```bash
cd examples/open_npu_soc/sw
make            # 使用 ../toolchain/prefix.mk
```

`make` 会生成 `gemm_8x8.elf` / `gemm_8x8.hex`（`$readmemh` 可读）。

## 注意

- 工具链压缩包和解压目录已在 `.gitignore` 里（约 1GB+，不进仓库）。
- `prefix.mk` 是生成物；换机器/换解压目录后重新跑 setup 即可。
