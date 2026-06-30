// ALU_constraint_coordinated_sequence.sv
// 自动生成的协调序列

`include "ALU_env_policy_factory.sv"

class ALU_env_coordinated_sequence extends uvm_virtual_sequence;
  `uvm_object_utils(ALU_env_coordinated_sequence)
  `uvm_declare_p_sequencer(ALU_env_virtual_sequencer)
  
  // 策略组合器
  ALU_env_policy_combinator policy_combo;
  
  // 事务队列
  ALU_env_policy_context queue[$];
  
  // 配置
  int num_transactions = 100;
  int queue_size = 10;
  int transaction_timeout_ms = 1000;
  
  // 统计
  int generated_count = 0;
  int processed_count = 0;
  
  function new(string name = "ALU_constraint_coordinated_sequence");
    super.new(name);
    policy_combo = ALU_env_policy_factory::create_from_plusargs();
  endfunction
  
  virtual task body();
    `uvm_info(get_name(), $sformatf("Starting coordinated sequence with %0d policies",
               policy_combo.policies.size()), UVM_MEDIUM)
    
    configure_from_plusargs();
    
    fork
      generate_transactions();
      process_transactions();
    join
    
    report_summary();
  endtask
  
  virtual task generate_transactions();
    for (int i = 0; i < num_transactions; i++) begin
      ALU_env_policy_context ctx = new();
      
      // 设置元数据
      ctx.scenario_name = get_name();
      ctx.iteration = i;
      ctx.total_iterations = num_transactions;
      ctx.timestamp = $time;
      
      // 创建基础事务
      create_base_transactions(ctx);
      
      // 应用策略约束
      policy_combo.apply(ctx);
      
      // 验证一致性
      if (!policy_combo.verify(ctx)) begin
        `uvm_error(get_name(), $sformatf("Policy verification failed at iteration %0d", i))
      end
      
      // 入队
      queue.push_back(ctx);
      generated_count++;
      
      // 队列流控
      while (queue.size() > queue_size) #1;
    end
    
    // 等待处理完成
    while (processed_count < generated_count) #1;
  endtask
  
  virtual task process_transactions();
    while (1) begin
      if (queue.size() > 0) begin
        ALU_env_policy_context ctx = queue.pop_front();
        
        fork
          begin
            fork
              send_transactions(ctx);
              begin
                #(transaction_timeout_ms * 1ms);
                `uvm_error(get_name(), $sformatf("Transaction timeout at iteration %0d",
                           ctx.iteration))
              end
            join_any
            disable fork;
          end
        join_none
        
        processed_count++;
      end
      #1;
    end
  endtask
  
  // 创建基础事务（可被继承重写）
  virtual function void create_base_transactions(ref ALU_env_policy_context ctx);
    // 创建并随机化各个事务

    ALU_cfg_transaction cfg_trans = ALU_cfg_transaction::type_id::create("cfg_trans");
    assert(cfg_trans.randomize());
    ctx.set_transaction("cfg", cfg_trans);

    ALU_weight_transaction weight_trans = ALU_weight_transaction::type_id::create("weight_trans");
    assert(weight_trans.randomize());
    ctx.set_transaction("weight", weight_trans);

    ALU_input_transaction input_trans = ALU_input_transaction::type_id::create("input_trans");
    assert(input_trans.randomize());
    ctx.set_transaction("input", input_trans);

    ALU_output_transaction output_trans = ALU_output_transaction::type_id::create("output_trans");
    assert(output_trans.randomize());
    ctx.set_transaction("output", output_trans);

  endfunction
  
  // 发送事务（可被继承重写）
  virtual task send_transactions(ref ALU_env_policy_context ctx);
    // 发送到对应的 sequencer

    begin
      ALU_cfg_transaction cfg_trans;
      $cast(cfg_trans, ctx.get_transaction("cfg"));
      if (cfg_trans != null && p_sequencer.cfg_sqr != null) begin
        start_item(cfg_trans, p_sequencer.cfg_sqr);
        finish_item(cfg_trans, p_sequencer.cfg_sqr);
      end
    end

    begin
      ALU_weight_transaction weight_trans;
      $cast(weight_trans, ctx.get_transaction("weight"));
      if (weight_trans != null && p_sequencer.weight_sqr != null) begin
        start_item(weight_trans, p_sequencer.weight_sqr);
        finish_item(weight_trans, p_sequencer.weight_sqr);
      end
    end

    begin
      ALU_input_transaction input_trans;
      $cast(input_trans, ctx.get_transaction("input"));
      if (input_trans != null && p_sequencer.input_sqr != null) begin
        start_item(input_trans, p_sequencer.input_sqr);
        finish_item(input_trans, p_sequencer.input_sqr);
      end
    end

    begin
      ALU_output_transaction output_trans;
      $cast(output_trans, ctx.get_transaction("output"));
      if (output_trans != null && p_sequencer.output_sqr != null) begin
        start_item(output_trans, p_sequencer.output_sqr);
        finish_item(output_trans, p_sequencer.output_sqr);
      end
    end

  endtask
  
  // 配置
  function void configure_from_plusargs();
    int num;
    if ($value$plusargs("ALU_ENV_NUM_TRANS=%0d", num))
      num_transactions = num;
    if ($value$plusargs("ALU_ENV_QUEUE_SIZE=%0d", num))
      queue_size = num;
    if ($value$plusargs("ALU_ENV_TIMEOUT_MS=%0d", num))
      transaction_timeout_ms = num;
  endfunction
  
  // 报告
  function void report_summary();
    `uvm_info(get_name(), "========================================", UVM_NONE)
    `uvm_info(get_name(), $sformatf("Generated: %0d, Processed: %0d", 
               generated_count, processed_count), UVM_NONE)
    policy_combo.report_stats();
    `uvm_info(get_name(), "========================================", UVM_NONE)
  endfunction
endclass