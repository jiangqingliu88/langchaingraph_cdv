# ════════════════════════════════════════════════════════════════
# 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
# ════════════════════════════════════════════════════════════════






# ════════════════════════════════════════════════════════════════
#   SignOffAI（功能签核） — 商标与权利声明
#   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
# 
#   文件:     Makefile
#   作者:     -

#   联系邮箱: -
#   联系邮箱: -
#   描述:     tool_uvm 自动生成
# 
#   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
#             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
# ════════════════════════════════════════════════════════════════


# ============================================================
# npu_sched_out 编译/仿真 Makefile（Questa / VCS 双后端）
# ============================================================
# 用法:
#   make                    # 编译（缺省 SIM=questa）
#   make compile SIM=vcs    # 用 VCS 编译
#   make run                # loopback 自闭环: 编译 + 仿真
#   make run SIM=vcs SEED=5
# 后端路径可覆盖: QUESTA / UVM_HOME / UVM_DPI / VCS / VCS_HOME

SIM ?= questa        # questa | vcs

AGENT  ?= npu_sched_out
SEED   ?= 1
OUTDIR ?= build/$(AGENT)

# ── Questa 后端 ──
QUESTA   ?= f:/questasim64_2024.1/win64
WORK      = $(OUTDIR)/work
UVM_HOME ?= f:/questasim64_2024.1/verilog_src/uvm-1.2/src
UVM_DPI  ?= f:/questasim64_2024.1/verilog_src/uvm-1.2/win64/uvm_dpi

# ── VCS 后端 ──
VCS     ?= vcs
VCS_HOME ?= /cad/tools/synopsys/vcs
SIMV     = $(OUTDIR)/simv

# ── loopback 自闭环（master-drive → slave-monitor）──
LB_SRC  = loopback/npu_sched_out_loopback_env.sv \
          loopback/npu_sched_out_loopback_scb.sv \
          loopback/npu_sched_out_loopback_test.sv \
          loopback/npu_sched_out_loopback_tb.sv
LB_TOP   = npu_sched_out_loopback_tb
LB_TEST  = npu_sched_out_loopback_test

.PHONY: all compile run clean compile_questa compile_vcs run_questa run_vcs

all: compile

# ── Questa: vlib + vlog ──
compile_questa:
	@mkdir -p $(OUTDIR)
	$(QUESTA)/vlib.exe $(WORK)
	$(QUESTA)/vlog.exe -work $(WORK) -sv +incdir+. +acc \
		+incdir+$(UVM_HOME) \
		$(UVM_HOME)/uvm_pkg.sv \
		-f filelist.f

# ── VCS: 单步编译（vcs 直接出 simv）──
compile_vcs:
	@mkdir -p $(OUTDIR)
	$(VCS) -sverilog +v2k -timescale=1ns/1ps \
		-debug_access+all -ntb_opts uvm-1.2 \
		+incdir+. -f filelist.f \
		-o $(SIMV) -l $(OUTDIR)/comp.log

# ── 仿真（loopback 自闭环）──
run: run_$(SIM)

run_questa: compile_questa
	$(QUESTA)/vlog.exe -work $(WORK) -sv +incdir+. +incdir+loopback \
		+incdir+$(UVM_HOME) $(LB_SRC)
	$(QUESTA)/vsim.exe -c -do "run -all; quit -f" \
		-sv_lib $(UVM_DPI) \
		-work $(WORK) -l $(OUTDIR)/$(LB_TOP)_s$(SEED).log \
		$(LB_TOP) +UVM_TESTNAME=$(LB_TEST) +ntb_random_seed=$(SEED)

run_vcs:
	@mkdir -p $(OUTDIR)
	$(VCS) -full64 -sverilog +v2k -timescale=1ns/1ps \
		-debug_access+all -ntb_opts uvm-1.2 \
		+incdir+. +incdir+loopback -f filelist.f $(LB_SRC) \
		-top $(LB_TOP) -o $(SIMV) -l $(OUTDIR)/comp.log
	$(SIMV) +UVM_TESTNAME=$(LB_TEST) +ntb_random_seed=$(SEED) \
		-l $(OUTDIR)/$(LB_TOP)_s$(SEED).log

compile: compile_$(SIM)

clean:
	rm -rf $(OUTDIR)
