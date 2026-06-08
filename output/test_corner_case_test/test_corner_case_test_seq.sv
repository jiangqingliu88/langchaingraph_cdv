# src/tools/testcase_gen/templates/sequence.sv.j2
// ============================================
// Sequence: test_corner_case_test_seq
// Project: project
// Policy Mode: APPLY_SEQUENTIAL
// Active Policies: precision_consistency, compute_mode
// Generated: auto
// ============================================

class test_corner_case_test_seq extends uvm_sequence #(ENV_transaction);
    `uvm_object_utils(test_corner_case_test_seq)
    
    // 策略注入
    ENV_policy_combinator policy_combo;
    string active_policies[$] = 'precision_consistency compute_mode';
    
    // 事务队列
    ENV_policy_context trans_queue[$];
    
    // 配置
    rand int num_transactions;
    rand int queue_depth;
    
    constraint num_c { num_transactions inside {[5:10]}; }
    constraint queue_c { queue_depth inside {[5:50]}; }
    
    function new(string name = "test_corner_case_test_seq");
        super.new(name);
    endfunction
    
    virtual task body();
        // 初始化策略
        if (policy_combo == null)
            policy_combo = ENV_policy_factory::create_from_plusargs();
        policy_combo.apply_mode = APPLY_SEQUENTIAL;
        
        `uvm_info(get_name(), $sformatf("Starting with %0d policies", 
                   active_policies.size()), UVM_MEDIUM)
        
        fork
            generate_transactions();
            execute_transactions();
        join
        
        policy_combo.report_stats();
    endtask
    
    virtual task generate_transactions();
        for (int i = 0; i < num_transactions; i++) begin
            ENV_policy_context ctx = new();
            ctx.iteration = i;
            ctx.total_iterations = num_transactions;
            ctx.timestamp = $time;
            
            // 创建事务

            
            // 应用策略
            policy_combo.apply(ctx);
            policy_combo.verify(ctx);
            
            trans_queue.push_back(ctx);
            while (trans_queue.size() > queue_depth) @(posedge clk);
        end
    endtask
    
    virtual task execute_transactions();
        while (trans_queue.size() > 0) begin
            ENV_policy_context ctx = trans_queue.pop_front();

        end
    endtask
    
endclass : test_corner_case_test_seq