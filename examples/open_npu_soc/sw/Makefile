# E203 bare-metal 固件（v0.1）
#
# 依赖 toolchain/prefix.mk（由 toolchain/setup_toolchain.py 生成）。
# 没有工具链时 make 会明确报错，不会假装编译成功。
-include ../toolchain/prefix.mk

RISCV_PREFIX ?= riscv-nuclei-elf-
CC      := $(RISCV_PREFIX)gcc
OBJCOPY := $(RISCV_PREFIX)objcopy
OBJDUMP := $(RISCV_PREFIX)objdump

ARCH    := -march=rv32imafdc -mabi=ilp32f
CFLAGS  := $(ARCH) -nostdlib -nostartfiles -ffreestanding -O2 -I. -T e203.ld
SRCS    := startup/startup.S tests/gemm_8x8.c

all: gemm_8x8.elf gemm_8x8.hex gemm_8x8.dump

gemm_8x8.elf: $(SRCS) e203.ld
	@command -v $(CC) >/dev/null 2>&1 || { \
	  echo "找不到 $(CC)。先运行 python ../toolchain/setup_toolchain.py"; exit 2; }
	$(CC) $(CFLAGS) $(SRCS) -o $@

gemm_8x8.hex: gemm_8x8.elf
	$(OBJCOPY) -O verilog $< $@

gemm_8x8.dump: gemm_8x8.elf
	$(OBJDUMP) -d $< > $@

clean:
	rm -f gemm_8x8.elf gemm_8x8.hex gemm_8x8.dump

.PHONY: all clean
