#!/bin/bash
export DC_HOME='/cad/tools/synopsys/syn_vX-2025.06-SP1'
export VCS_HOME='/cad/tools/synopsys/vcs_vO-2020.03-SP1'
export UVM_HOME='/cad/tools/synopsys/vcs_vO-2020.03-SP1/etc/uvm-1.2'
export EMAN_TOP_RUN_DIR='D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2'
export EMAN_CONFIG_NAME='p2'
export EMAN_SESSION_NAME='p2'
export EMAN_BUILD_NAME='build_npu_sched_dut'
export EMAN_BUILD_PATH='build_build_npu_sched_dut'
export EMAN_COMPILE_DIR='D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut'
export EMAN_SIMV='D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut/simv'
export EMAN_DEBUG_SIMV='D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut/simv_debug'
export EMAN_RUN_DIR='D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001'
export EMAN_CM_DIR='D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001/cov'
export EMAN_ERROR_PATTERN='ERROR|FATAL|UVM_ERROR|FAILED'
export EMAN_TEST_NAME='tp_npusch_d_opcode_dma_read'
export EMAN_TESTCASE='tp_npusch_d_opcode_dma_read_seed_8001'
export EMAN_CM_NAME='tp_npusch_d_opcode_dma_read_seed_8001'
export EMAN_LOG_FILE='D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001/sim.log'
export EMAN_DEBUG_LOG_FILE='D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001/sim_debug.log'
export EMAN_TEST_PATH='build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001'
export EMAN_TEST_GROUP_PATH='tp_npusch_d_opcode_dma_read_seed_8001'
export EMAN_RANDOM='8001'
mkdir -p D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001/waves
start_time=$(date +%s)
vsim -c -sv_lib f:/questasim64_2024.1/uvm-1.2/win64/uvm_dpi -onfinish stop -work D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut/work npu_sched_bench_tb_top +UVM_TESTNAME=npu_sched_env_d_opcode_pDMA_READ_test +ntb_random_seed=8001 -l sim_vsim.log  -do "log -r /*; run -all; quit -f" -coverage -coverstore ${EMAN_CM_DIR}/${EMAN_TEST_NAME} -testname ${EMAN_TEST_NAME} -voptargs=+acc -qwavedb=+signal+class+wavefile=${EMAN_RUN_DIR}/waves/${EMAN_TEST_NAME}.db  ; [ -s sim_vsim.log ] && ! grep -qE "UVM_ERROR : *[1-9]|UVM_FATAL : *[1-9]|FATAL ERROR|Errors: *[1-9]" sim_vsim.log && { grep -qE "(\[SCB_DUT\]|Scoreboard:).*mismatched=0" sim_vsim.log || { echo "NO_CHECKER_EVIDENCE: 没有比对结论（真 pass 要求 SCB 报 mismatched=0）"; exit 1; }; } > sim.log 2>&1
ret=$?
end_time=$(date +%s)
sim_time=$((end_time - start_time))
echo "SIM_TIME=$sim_time" > sim_time.log
if [ -f D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001/waves/tp_npusch_d_opcode_dma_read.db ]; then
    echo "WAVE_PATH=D:/SignOffAI/output_e2e_final4_jiang_20261104_044624/regression_run/p2/build_build_npu_sched_dut/test_tp_npusch_d_opcode_dma_read_seed_8001/waves/tp_npusch_d_opcode_dma_read.db" > wave.log
else
    echo "WAVE_PATH=NOT_FOUND" > wave.log
fi
exit $ret
