// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_coordinated_sequence.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// npu_sched_env_coordinated_sequence.sv
// 自动生成的协调序列

`include "npu_sched_env_policy_factory.sv"

// **不是 `uvm_virtual_sequence`** —— UVM 里没有这个基类（那个名字在
// base_pkg 里也不存在）。写了它的后果是：这些文件一旦被 include 就
// "Undefined type"，而在此之前它们从没被 include 过，所以一直没暴露。
class npu_sched_env_coordinated_sequence extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(npu_sched_env_coordinated_sequence)
  `uvm_declare_p_sequencer(npu_sched_env_virtual_sequencer)
  
  // 策略组合器
  npu_sched_env_policy_combinator policy_combo;
  
  // 事务队列
  npu_sched_env_policy_context queue[$];
  
  // 配置
  int num_transactions = 100;
  int queue_size = 10;
  int transaction_timeout_ms = 1000;
  
  // 统计
  int generated_count = 0;
  int processed_count = 0;
  
  function new(string name = "npu_sched_env_coordinated_sequence");
    super.new(name);
    // 约束策略**优先取模型给的批次策略**（batch test 挂的 `batch_policy`），
    // 没有才退回 plusargs（`+POLICY_LIST`）。见 factory 里
    // `create_from_batch` / `create_from_plusargs` 的注释 —— 前者是"模型说了算"，
    // 后者是"回归命令行说了算"。
    policy_combo = npu_sched_env_policy_factory::create_from_batch();
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
      npu_sched_env_policy_context ctx = new();
      
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
      // **写成 `begin #1; end`**：`while (cond) #1;` 在 vlog 里报
      // "near #: syntax error, unexpected #, expecting ;"（这些文件以前
      // 从没进过编译，所以一直没暴露）。
      while (queue.size() > queue_size) begin
        #1;
      end
    end

    // 等待处理完成
    while (processed_count < generated_count) begin
      #1;
    end
  endtask
  
  virtual task process_transactions();
    // **不能 `while (1)`**：body() 用 `fork generate / process ... join` 等两边
    // 都结束；process 永不返回 → body 永不返回 → objection 永不释放 →
    // 一路挂到 UVM 的 PH_TIMEOUT。生成完、且全部处理完就退出。
    while (!(generated_count > 0 && processed_count >= generated_count)) begin
      if (queue.size() > 0) begin
        npu_sched_env_policy_context ctx = queue.pop_front();
        
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
  virtual function void create_base_transactions(ref npu_sched_env_policy_context ctx);
    // 创建并随机化各个事务
    // **声明全部前置**：SV 不允许在语句之后再声明（多个事务时第二个就会报
    // "Illegal declaration after the statement"）。

    npu_sched_in_master_seq_item npu_sched_in_trans;

    npu_sched_out_master_seq_item npu_sched_out_trans;


    npu_sched_in_trans = npu_sched_in_master_seq_item::type_id::create("npu_sched_in_trans");
    assert(npu_sched_in_trans.randomize());
    ctx.set_transaction("npu_sched_in", npu_sched_in_trans);

    npu_sched_out_trans = npu_sched_out_master_seq_item::type_id::create("npu_sched_out_trans");
    assert(npu_sched_out_trans.randomize());
    ctx.set_transaction("npu_sched_out", npu_sched_out_trans);

  endfunction
  
  // 发送事务（可被继承重写）
  virtual task send_transactions(ref npu_sched_env_policy_context ctx);
    // 发送到对应的 sequencer

    begin
      npu_sched_in_master_seq_item npu_sched_in_trans;
      $cast(npu_sched_in_trans, ctx.get_transaction("npu_sched_in"));
      if (npu_sched_in_trans != null && p_sequencer.npu_sched_in_sqr != null) begin
        // **第二个参数是 `set_priority`（int），不是 sequencer** ——
        // `start_item(item, sqr)` 会把 sequencer 塞进 int 形参，vsim 报
        // "Actual input arg ... for formal 'set_priority' ... is not compatible
        //  with 'int'"。签名是 `(item, set_priority = -1, sequencer = null)`。
        start_item(npu_sched_in_trans, -1, p_sequencer.npu_sched_in_sqr);
        // `finish_item` **只有两个形参**（item, set_priority）：sequencer 由
        // 上一条 `start_item` 记住。给三个 vlog/vsim 报 "Too many arguments"。
        finish_item(npu_sched_in_trans, -1);
      end
    end

    begin
      npu_sched_out_master_seq_item npu_sched_out_trans;
      $cast(npu_sched_out_trans, ctx.get_transaction("npu_sched_out"));
      if (npu_sched_out_trans != null && p_sequencer.npu_sched_out_sqr != null) begin
        // **第二个参数是 `set_priority`（int），不是 sequencer** ——
        // `start_item(item, sqr)` 会把 sequencer 塞进 int 形参，vsim 报
        // "Actual input arg ... for formal 'set_priority' ... is not compatible
        //  with 'int'"。签名是 `(item, set_priority = -1, sequencer = null)`。
        start_item(npu_sched_out_trans, -1, p_sequencer.npu_sched_out_sqr);
        // `finish_item` **只有两个形参**（item, set_priority）：sequencer 由
        // 上一条 `start_item` 记住。给三个 vlog/vsim 报 "Too many arguments"。
        finish_item(npu_sched_out_trans, -1);
      end
    end

  endtask
  
  // 配置
  function void configure_from_plusargs();
    int num;
    if ($value$plusargs("NPU_SCHED_ENV_NUM_TRANS=%0d", num))
      num_transactions = num;
    if ($value$plusargs("NPU_SCHED_ENV_QUEUE_SIZE=%0d", num))
      queue_size = num;
    if ($value$plusargs("NPU_SCHED_ENV_TIMEOUT_MS=%0d", num))
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
