# src/tools/testcase_gen/templates/run_script.sh.j2
#!/bin/bash
# Run: test_error_handling_test
# Policy Mode: APPLY_SEQUENTIAL
# Active Policies: precision_consistency compute_mode

vsim -c -do "run -all" \
    +UVM_TESTNAME=test_error_handling_test \
    +ENV_POLICY_MODE=APPLY_SEQUENTIAL \
    +ENV_POLICY_LIST=precision_consistency,compute_mode