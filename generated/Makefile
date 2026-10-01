# ════════════════════════════════════════════════════════════════
# 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
# ════════════════════════════════════════════════════════════════




# ════════════════════════════════════════════════════════════════
#   SignOffAI（功能签核） — 商标与权利声明
#   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
# 
#   文件:     Makefile
#   作者:     -
#   创建时间: 2026-09-15 15:43:52
#   修改时间: 2026-09-15 15:43:52
#   联系邮箱: -
#   描述:     tool_uvm 自动生成
# 
#   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
#             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
# ════════════════════════════════════════════════════════════════


# ============================================================
# APB_env 整环境编译/仿真 Makefile（Questa / VCS 双后端）
# ============================================================
# 用法（在生成目录根执行）:
#   make                                # 编译（缺省 SIM=questa）
#   make compile SIM=vcs                # VCS 编译
#   make run TEST=APB_env_base_test     # 编译 + 仿真一个测试
#   make run SIM=vcs SEED=5 TEST=APB_env_direct_test
#   make compile DUT=rtl/dut.sv         # 追加 DUT 源码（单文件，可传多个）
# 后端路径可覆盖: QUESTA / UVM_HOME / UVM_DPI / VCS / BASE_PKG

SIM ?= questa        # questa | vcs

ENV    ?= APB_env
BENCH  ?= APB_bench
TEST   ?= APB_env_base_test
SEED   ?= 1
OUTDIR ?= build
DUT    ?=
COV    ?= 0

# ── Questa 后端 ──
QUESTA   ?= f:/questasim64_2024.1/win64
WORK      = $(OUTDIR)/work
UVM_HOME ?= f:/questasim64_2024.1/verilog_src/uvm-1.2/src
UVM_DPI  ?= f:/questasim64_2024.1/verilog_src/uvm-1.2/win64/uvm_dpi

# ── VCS 后端 ──
VCS  ?= vcs
SIMV  = $(OUTDIR)/simv

# ── Base PKG（clk_rst + scoreboard 组件族；生成器渲染相对路径）──
BASE_PKG ?= ../src/tools/uvm_tools/tool_uvm/base_pkg

# ── 编译文件清单（相对路径，自包含）──
# 顺序: base_pkg → interface agents → harness → env → tests → seqs → tb_top
SRC = \
  +incdir+$(BASE_PKG)/clk_and_rst \
  $(BASE_PKG)/clk_and_rst/clk_and_rst_pkg.sv \
  +incdir+$(BASE_PKG)/scb \
  $(BASE_PKG)/scb/scb_pkg.sv \
  +incdir+$(BASE_PKG)/common_typedefs \
  $(BASE_PKG)/common_typedefs/common_typedefs_pkg.sv \
  +incdir+agents/apb_agent \
  agents/apb_agent/1_interface/apb_if.sv \
  agents/apb_agent/1_interface/apb_system_if.sv \
  agents/apb_agent/apb_parameters_pkg.sv \
  agents/apb_agent/apb_typedefs_pkg.sv \
  agents/apb_agent/apb_pkg.sv \
  bench/apb_harness.sv \
  +incdir+env \
  env/$(ENV)_parameters_pkg.sv \
  env/$(ENV)_pkg.sv \
  +incdir+env/tests \
  env/tests/$(ENV)_test_pkg.sv \
  +incdir+env/seqs \
  env/seqs/$(ENV)_seq_pkg.sv \
  bench/$(BENCH)_tb_top.sv \
  $(DUT)

# ── 覆盖率选项 ──
COV_FLAG_Q =
COV_FLAG_V =
COV_FLAG_Q_RUN =
ifeq ($(COV),1)
COV_FLAG_Q = +cover=bcesf
COV_FLAG_V = -cm line+cond+fsm+tgl+branch
COV_FLAG_Q_RUN = -coverage
endif

# ── Questa 仿真 do 脚本（COV=1 时退出前保存 ucdb）──
VSIM_DO = run -all; quit -f
ifeq ($(COV),1)
VSIM_DO = coverage save -onexit $(OUTDIR)/$(TEST)_s$(SEED).ucdb; run -all; quit -f
endif

.PHONY: all compile run clean compile_questa compile_vcs run_questa run_vcs

all: compile

# ── Questa: vlib + vlog ──
compile_questa:
	@mkdir -p $(OUTDIR)
	$(QUESTA)/vlib.exe $(WORK)
	$(QUESTA)/vlog.exe -work $(WORK) -sv -mfcu +acc \
		+incdir+$(UVM_HOME) $(UVM_HOME)/uvm_pkg.sv \
		$(COV_FLAG_Q) \
		$(SRC)

# ── VCS: 单步编译（vcs 直接出 simv）──
compile_vcs:
	@mkdir -p $(OUTDIR)
	$(VCS) -full64 -sverilog +v2k -timescale=1ns/1ps \
		-debug_access+all -ntb_opts uvm-1.2 \
		$(COV_FLAG_V) \
		$(SRC) \
		-top $(BENCH)_tb_top -o $(SIMV) -l $(OUTDIR)/comp.log

# ── 仿真 ──
run: run_$(SIM)

run_questa: compile_questa
	$(QUESTA)/vsim.exe -c -do "$(VSIM_DO)" \
		-sv_lib $(UVM_DPI) $(COV_FLAG_Q_RUN) \
		-work $(WORK) -l $(OUTDIR)/$(TEST)_s$(SEED).log \
		$(BENCH)_tb_top +UVM_TESTNAME=$(TEST) +ntb_random_seed=$(SEED)

run_vcs: compile_vcs
	$(SIMV) +UVM_TESTNAME=$(TEST) +ntb_random_seed=$(SEED) \
		$(COV_FLAG_V) -cm_dir $(OUTDIR)/$(TEST)_s$(SEED).vdb \
		-l $(OUTDIR)/$(TEST)_s$(SEED).log

compile: compile_$(SIM)

clean:
	rm -rf $(OUTDIR)
