#!/bin/bash
echo "Running regression in output_e2e_final4_jiang_20261104_044624\regression_run\p1 (mode=local)"
set -e
echo "--- Build build_npu_sched_dut ---"
cd build_build_npu_sched_dut && ./build.sh && cd ..
for testdir in build_build_npu_sched_dut/test_*; do
  if [ -d "$testdir" ]; then
    cd $testdir && ./sim.sh && cd ../..
  fi
done
echo "--- Build build_npu_sched_npu_sched_in_loopback ---"
cd build_build_npu_sched_npu_sched_in_loopback && ./build.sh && cd ..
for testdir in build_build_npu_sched_npu_sched_in_loopback/test_*; do
  if [ -d "$testdir" ]; then
    cd $testdir && ./sim.sh && cd ../..
  fi
done
echo "--- Build build_npu_sched_npu_sched_out_loopback ---"
cd build_build_npu_sched_npu_sched_out_loopback && ./build.sh && cd ..
for testdir in build_build_npu_sched_npu_sched_out_loopback/test_*; do
  if [ -d "$testdir" ]; then
    cd $testdir && ./sim.sh && cd ../..
  fi
done
