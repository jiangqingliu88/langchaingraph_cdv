# 用法: make AGENT={{ agent.name }} [SEED=1] [ITEMS=50]

AGENT  ?= UART_in
SEED   ?= 1
ITEMS  ?= 20
OUTDIR ?= loopback_out/$(AGENT)

QUESTA = f:/questasim64_2024.1/win64
WORK   = $(OUTDIR)/work

SRC    = ../agents/$(AGENT)_pkg.sv        \
         ../agents/$(AGENT)_interface.sv   \
         ../agents/$(AGENT)_agent.sv       \
         $(AGENT)_loopback_env.sv          \
         $(AGENT)_loopback_scb.sv          \
         $(AGENT)_loopback_test.sv         \
         $(AGENT)_loopback_tb.sv

.PHONY: all compile run clean

all: compile run

compile:
	@mkdir -p $(OUTDIR)
	$(QUESTA)/vlib.exe $(WORK)
	$(QUESTA)/vlog.exe -work $(WORK) -sv +incdir+../agents +incdir+. +acc \
		+incdir+f:/questasim64_2024.1/verilog_src/uvm-1.2/src \
		f:/questasim64_2024.1/verilog_src/uvm-1.2/src/uvm_pkg.sv \
		$(SRC)

run:
	$(QUESTA)/vopt.exe +cover=bcesft -work $(WORK) $(AGENT)_loopback_tb -o $(AGENT)_loopback_opt
	$(QUESTA)/vsim.exe -c -coverage \
		-do "run -all; coverage save $(OUTDIR)/loopback.ucdb; quit -f" \
		-work $(WORK) $(AGENT)_loopback_opt \
		+UVM_TESTNAME=$(AGENT)_loopback_test +uvm_set_verbosity=*_LOOPBACK*_UVM_MEDIUM

cov:
	$(QUESTA)/vcover.exe report -details $(OUTDIR)/loopback.ucdb

clean:
	rm -rf $(OUTDIR)
