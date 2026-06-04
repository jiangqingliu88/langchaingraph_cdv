# src/tools/testcase_gen/templates/run_script.sh.j2
#!/bin/bash
# Run: test_error_injection_test
# Policy Mode: APPLY_FIRST_MATCH
# Active Policies: boundary_overflow concurrent_access

vsim -c -do "run -all" \
    +UVM_TESTNAME=test_error_injection_test \
    +ENV_POLICY_MODE=APPLY_FIRST_MATCH \
    +ENV_POLICY_LIST=boundary_overflow,concurrent_access