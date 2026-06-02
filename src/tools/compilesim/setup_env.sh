#!/bin/bash
# ============================================================
# UVM 验证环境变量 + 编译仿真快捷命令
#
# 用法:
#   source src/tools/compilesim/setup_env.sh
#   uvm_compile    # 编译
#   uvm_run        # 仿真
# ============================================================
export GENDIR="D:/tmp/uart_gen"
export PROJ_ROOT="D:/cdv_a"
export QUESTA_HOME="f:/questasim64_2024.1/win64"
export PATH="$QUESTA_HOME:$PATH"

echo "UVM 环境已设置:"
echo "  GENDIR     = $GENDIR"
echo "  PROJ_ROOT  = $PROJ_ROOT"

# ---- 编译 ----
uvm_compile() {
    local work_dir="${GENDIR}/build/work"
    mkdir -p "$(dirname "$work_dir")"
    "$QUESTA_HOME/vlib.exe" "$work_dir"
    "$QUESTA_HOME/vlog.exe" -work "$work_dir" -sv -timescale=1ns/1ps -f "${GENDIR}/filelist.f"
}

# ---- 仿真 ----
uvm_run() {
    local work_dir="${GENDIR}/build/work"
    local test_name="${1:-uart_base_test}"
    "$QUESTA_HOME/vsim.exe" -c -do "run -all; quit" \
        -work "$work_dir" \
        uart_bench_tb_top \
        "+UVM_TESTNAME=$test_name"
}
