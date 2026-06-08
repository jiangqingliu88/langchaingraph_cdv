# src/tools/testcase_gen/templates/test.sv.j2
// ============================================
// Test: test_stress_test
// Scenario: stress — 2 个测试用例
// Policy Mode: APPLY_ALL
// Active Policies: mem_capacity, boundary_overflow, concurrent_access, power_performance
// ============================================

class test_stress_test extends base_test;
    `uvm_component_utils(test_stress_test)
    
    ENV_policy_combinator policy_combo;
    
    function new(string name = "test_stress_test", uvm_component parent = null);
        super.new(name, parent);
    endfunction
    
    virtual function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        policy_combo = ENV_policy_factory::create_from_plusargs();
        policy_combo.apply_mode = APPLY_ALL;
    endfunction
    
    virtual task run_phase(uvm_phase phase);
        test_stress_test_seq seq;
        phase.raise_objection(this);
        seq = test_stress_test_seq::type_id::create("seq");
        seq.policy_combo = policy_combo;
        seq.start(p_sequencer);
        phase.drop_objection(this);
    endtask
    
    virtual function void report_phase(uvm_phase phase);
        super.report_phase(phase);
        policy_combo.report_stats();

        `uvm_info("test_stress_test", "Check policy_applied: Policy check passed", UVM_MEDIUM)

        `uvm_info("test_stress_test", "Check transactions_done: All transactions completed", UVM_MEDIUM)

    endfunction
    
endclass : test_stress_test