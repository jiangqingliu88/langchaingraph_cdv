# ════════════════════════════════════════════════════════════════
# 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
# ════════════════════════════════════════════════════════════════




# ════════════════════════════════════════════════════════════════
#   SignOffAI（功能签核） — 商标与权利声明
#   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
# 
#   文件:     Makefile
#   作者:     -
#   创建时间: 2026-09-09 17:58:44
#   修改时间: 2026-09-09 17:58:44
#   联系邮箱: -
#   描述:     tool_uvm 自动生成
# 
#   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
#             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
# ════════════════════════════════════════════════════════════════


# ============================================================
# APB 编译/仿真 Makefile
# ============================================================

AGENT  ?= APB
SEED   ?= 1
OUTDIR ?= build/$(AGENT)

QUESTA   = f:/questasim64_2024.1/win64
WORK     = $(OUTDIR)/work
UVM_HOME = f:/questasim64_2024.1/verilog_src/uvm-1.2/src

SRC = 1_interface/APB_if.sv \
      1_interface/APB_system_if.sv \
      APB_pkg.sv

.PHONY: all compile clean

all: compile

compile:
	@mkdir -p $(OUTDIR)
	$(QUESTA)/vlib.exe $(WORK)
	$(QUESTA)/vlog.exe -work $(WORK) -sv +incdir+. +acc \
		+incdir+$(UVM_HOME) \
		$(UVM_HOME)/uvm_pkg.sv \
		$(SRC)

clean:
	rm -rf $(OUTDIR)
