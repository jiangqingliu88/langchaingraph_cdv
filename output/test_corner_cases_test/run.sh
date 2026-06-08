# src/tools/testcase_gen/templates/run_script.sh.j2
#!/bin/bash
# Run: test_corner_cases_test
# Policy Mode: APPLY_WEIGHTED
# Active Policies: boundary_overflow mem_capacity data_dependency

vsim -c -do "run -all" \
    +UVM_TESTNAME=test_corner_cases_test \
    +ENV_POLICY_MODE=APPLY_WEIGHTED \
    +ENV_POLICY_LIST=boundary_overflow,mem_capacity,data_dependency