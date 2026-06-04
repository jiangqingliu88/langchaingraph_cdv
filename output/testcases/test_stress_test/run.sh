# src/tools/testcase_gen/templates/run_script.sh.j2
#!/bin/bash
# Run: test_stress_test
# Policy Mode: APPLY_ALL
# Active Policies: mem_capacity boundary_overflow concurrent_access power_performance

vsim -c -do "run -all" \
    +UVM_TESTNAME=test_stress_test \
    +ENV_POLICY_MODE=APPLY_ALL \
    +ENV_POLICY_LIST=mem_capacity,boundary_overflow,concurrent_access,power_performance