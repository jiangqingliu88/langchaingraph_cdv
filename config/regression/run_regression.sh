#!/bin/bash
# =============================================================================
# QuestaSim 回归测试 - 统一启动脚本
# =============================================================================
# 用法:
#   ./run_regression.sh smoke          # 冒烟测试 (本地)
#   ./run_regression.sh alu            # ALU 全量回归 (本地)
#   ./run_regression.sh apb_uart       # APB+UART 回归 (本地)
#   ./run_regression.sh alu_lsf        # ALU 回归 (LSF 集群)
#   ./run_regression.sh smoke_mock     # 冒烟测试 (模拟/干跑)
#   ./run_regression.sh alu_inc        # ALU 增量回归
#
# 环境要求:
#   - Python 3.8+
#   - QuestaSim 在 PATH 中 (vlog, vsim, vlib 可用)
#   - LSF 模式需 bsub/bjobs 可用
# =============================================================================

set -e

# ---- 路径配置 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FRAMEWORK_DIR="${PROJ_ROOT}/src/tools/regression_tools/regression_framwork"
REGRESSION_PY="${FRAMEWORK_DIR}/regression.py"
CONFIG_DIR="${SCRIPT_DIR}"

# ---- 颜色输出 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }

# ---- 检查前置条件 ----
check_prereqs() {
    if [ ! -f "$REGRESSION_PY" ]; then
        err "regression.py not found at: $REGRESSION_PY"
        exit 1
    fi
    if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
        err "Python not found in PATH"
        exit 1
    fi
    PYTHON=$(command -v python3 || command -v python)
    info "Using Python: $PYTHON"
    info "Framework: $REGRESSION_PY"
}

# ---- 运行回归 ----
run_regression() {
    local config="$1"
    local mode="$2"
    local extra_args="${@:3}"

    info "Config:   ${config}"
    info "Mode:     ${mode}"
    info "Extra:    ${extra_args}"

    cd "$PROJ_ROOT"
    $PYTHON "$REGRESSION_PY" \
        --config "${CONFIG_DIR}/${config}" \
        --action all \
        --mode "$mode" \
        $extra_args

    ok "Regression finished. Check output directory for reports."
}

# ---- 主入口 ----
check_prereqs

case "${1:-help}" in
    # ============ 本地执行 ============
    smoke)
        run_regression "questa_smoke.yaml" "local" --tags smoke
        ;;
    alu)
        run_regression "questa_alu_full.yaml" "local"
        ;;
    apb_uart)
        run_regression "questa_apb_uart.yaml" "local"
        ;;

    # ============ 模拟/干跑 ============
    smoke_mock)
        run_regression "questa_smoke.yaml" "mock" --dry-run
        ;;
    alu_mock)
        run_regression "questa_alu_full.yaml" "mock" --dry-run
        ;;
    apb_uart_mock)
        run_regression "questa_apb_uart.yaml" "mock" --dry-run
        ;;

    # ============ LSF 集群 ============
    smoke_lsf)
        run_regression "questa_smoke.yaml" "lsf" --lsf-queue short --lsf-resource "rusage[mem=4096]"
        ;;
    alu_lsf)
        run_regression "questa_alu_full.yaml" "lsf" --lsf-queue normal --lsf-resource "rusage[mem=8192]"
        ;;
    apb_uart_lsf)
        run_regression "questa_apb_uart.yaml" "lsf" --lsf-queue normal --lsf-resource "rusage[mem=8192]"
        ;;

    # ============ 增量回归 ============
    alu_inc)
        run_regression "questa_alu_full.yaml" "local" --incremental
        ;;
    apb_uart_inc)
        run_regression "questa_apb_uart.yaml" "local" --incremental
        ;;

    # ============ 仅生成脚本 ============
    smoke_gen)
        $PYTHON "$REGRESSION_PY" --config "${CONFIG_DIR}/questa_smoke.yaml" --action generate
        ok "Scripts generated. Check regression_mock_* directory."
        ;;
    alu_gen)
        $PYTHON "$REGRESSION_PY" --config "${CONFIG_DIR}/questa_alu_full.yaml" --action generate
        ok "Scripts generated."
        ;;
    apb_uart_gen)
        $PYTHON "$REGRESSION_PY" --config "${CONFIG_DIR}/questa_apb_uart.yaml" --action generate
        ok "Scripts generated."
        ;;

    # ============ 按标签过滤 ============
    alu_smoke)
        run_regression "questa_alu_full.yaml" "local" --tags smoke
        ;;
    alu_matrix)
        run_regression "questa_alu_full.yaml" "local" --tags matrix
        ;;
    alu_stress)
        run_regression "questa_alu_full.yaml" "local" --tags stress
        ;;
    uart_baud)
        run_regression "questa_apb_uart.yaml" "local" --tags baud
        ;;

    # ============ 重跑失败用例 ============
    rerun)
        if [ -z "$2" ]; then
            err "Usage: $0 rerun <regression_output_dir>"
            exit 1
        fi
        $PYTHON "$REGRESSION_PY" --rerun-failed "$2"
        ;;

    # ============ 帮助 ============
    help|*)
        echo ""
        echo "QuestaSim Regression Runner"
        echo "==========================="
        echo ""
        echo "Usage: $0 <command> [args]"
        echo ""
        echo "Local execution:"
        echo "  smoke         Run smoke tests locally"
        echo "  alu           Run full ALU regression locally"
        echo "  apb_uart      Run APB+UART regression locally"
        echo ""
        echo "Mock/Dry-run (no actual simulation):"
        echo "  smoke_mock    Print smoke commands without running"
        echo "  alu_mock      Print ALU commands without running"
        echo "  apb_uart_mock Print APB+UART commands without running"
        echo ""
        echo "LSF cluster:"
        echo "  smoke_lsf     Submit smoke tests to LSF"
        echo "  alu_lsf       Submit ALU regression to LSF"
        echo "  apb_uart_lsf  Submit APB+UART regression to LSF"
        echo ""
        echo "Incremental (Git-based):"
        echo "  alu_inc       Incremental ALU regression"
        echo "  apb_uart_inc  Incremental APB+UART regression"
        echo ""
        echo "Generate only (no execution):"
        echo "  smoke_gen     Generate smoke test scripts"
        echo "  alu_gen       Generate ALU regression scripts"
        echo "  apb_uart_gen  Generate APB+UART regression scripts"
        echo ""
        echo "Tag filters:"
        echo "  alu_smoke     ALU tests tagged 'smoke'"
        echo "  alu_matrix    ALU tests tagged 'matrix'"
        echo "  alu_stress    ALU tests tagged 'stress'"
        echo "  uart_baud     UART tests tagged 'baud'"
        echo ""
        echo "Other:"
        echo "  rerun <dir>   Rerun failed tests from previous regression"
        echo ""
        ;;
esac
