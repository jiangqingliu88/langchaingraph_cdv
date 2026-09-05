// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     apb_cons_coordinated_sequence.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// apb_cons_coordinated_sequence.sv
// 自动生成的协调序列

`include "APB_env_policy_factory.sv"

class APB_env_coordinated_sequence extends uvm_virtual_sequence;
  `uvm_object_utils(APB_env_coordinated_sequence)
  `uvm_declare_p_sequencer(APB_env_virtual_sequencer)
  
  // 策略组合器
  APB_env_policy_combinator policy_combo;
  
  // 事务队列
  APB_env_policy_context queue[$];
  
  // 配置
  int num_transactions = 100;
  int queue_size = 10;
  int transaction_timeout_ms = 1000;
  
  // 统计
  int generated_count = 0;
  int processed_count = 0;
  
  function new(string name = "apb_cons_coordinated_sequence");
    super.new(name);
    policy_combo = APB_env_policy_factory::create_from_plusargs();
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
      APB_env_policy_context ctx = new();
      
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
        APB_env_policy_context ctx = queue.pop_front();
        
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
  virtual function void create_base_transactions(ref APB_env_policy_context ctx);
    // 创建并随机化各个事务

    APB_master_seq_item apb_master_trans = APB_master_seq_item::type_id::create("apb_master_trans");
    assert(apb_master_trans.randomize());
    ctx.set_transaction("apb_master", apb_master_trans);

  endfunction
  
  // 发送事务（可被继承重写）
  virtual task send_transactions(ref APB_env_policy_context ctx);
    // 发送到对应的 sequencer

    begin
      APB_master_seq_item apb_master_trans;
      $cast(apb_master_trans, ctx.get_transaction("apb_master"));
      if (apb_master_trans != null && p_sequencer.apb_master_sqr != null) begin
        start_item(apb_master_trans, p_sequencer.apb_master_sqr);
        finish_item(apb_master_trans, p_sequencer.apb_master_sqr);
      end
    end

  endtask
  
  // 配置
  function void configure_from_plusargs();
    int num;
    if ($value$plusargs("APB_ENV_NUM_TRANS=%0d", num))
      num_transactions = num;
    if ($value$plusargs("APB_ENV_QUEUE_SIZE=%0d", num))
      queue_size = num;
    if ($value$plusargs("APB_ENV_TIMEOUT_MS=%0d", num))
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
