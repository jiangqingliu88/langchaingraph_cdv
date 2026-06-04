// ============================================================
// Virtual Sequencer: uart_env_virtual_sequencer
// 支持多 Agent 仲裁和调度
// ============================================================

`ifndef UART_ENV_VIRTUAL_SEQUENCER_SV
`define UART_ENV_VIRTUAL_SEQUENCER_SV

class uart_env_virtual_sequencer extends uvm_sequencer #(uvm_sequence_item);
  `uvm_component_utils(uart_env_virtual_sequencer)

  // ═══════════════════════════════════════════════════════════════
  // 1. 子 Sequencer 句柄
  // ═══════════════════════════════════════════════════════════════
  // AXI_in Agent Sequencer
  uvm_sequencer #(AXI_in_seq_item) AXI_in_sqr;
  // UART_in Agent Sequencer
  uvm_sequencer #(UART_in_seq_item) UART_in_sqr;
  // UART_out Agent Sequencer
  uvm_sequencer #(UART_out_seq_item) UART_out_sqr;
  
  // Clock & Reset Sequencer（如果启用）


  // ═══════════════════════════════════════════════════════════════
  // 1.5 has_sequence 辅助 —— UVM-1.2 中 uvm_sequencer_base 无此 API
  //    通过 grab/lock 状态判断是否有活跃 sequence 占用
  // ═══════════════════════════════════════════════════════════════

  protected function bit has_sequence(uvm_sequencer_base sqr);
    // uvm_sequencer_base 在 UVM-1.2 中无 grab/lock 查询 API
    // 非空即视为可用（子类可覆盖做更精细判断）
    return (sqr != null);
  endfunction

  // ═══════════════════════════════════════════════════════════════
  // 2. 仲裁策略枚举
  // ═══════════════════════════════════════════════════════════════
  
  typedef enum {
    ROUND_ROBIN,        // 轮询仲裁 - 公平轮流
    PRIORITY_BASED,     // 优先级仲裁 - 高优先级优先
    WEIGHTED_RR,        // 加权轮询 - 按权重分配
    TOKEN_RING,         // 令牌环 - 令牌传递
    SEQUENTIAL,         // 顺序执行 - 非并发
    USER_DEFINED        // 用户自定义
  } arb_policy_e;
  
  // 当前仲裁策略
  arb_policy_e arb_policy = PRIORITY_BASED;
  
  // ═══════════════════════════════════════════════════════════════
  // 3. 优先级和权重配置
  // ═══════════════════════════════════════════════════════════════
  // AXI_in 优先级（数值越小优先级越高）
  int AXI_in_priority = 5;
  // AXI_in 权重（用于加权轮询）
  int AXI_in_weight = 1;
  // UART_in 优先级（数值越小优先级越高）
  int UART_in_priority = 5;
  // UART_in 权重（用于加权轮询）
  int UART_in_weight = 1;
  // UART_out 优先级（数值越小优先级越高）
  int UART_out_priority = 5;
  // UART_out 权重（用于加权轮询）
  int UART_out_weight = 1;

  // ═══════════════════════════════════════════════════════════════
  // 4. 内部状态变量
  // ═══════════════════════════════════════════════════════════════
  
  // 轮询计数器
  protected int round_robin_counter = 0;
  
  // 加权轮询剩余权重
  protected int AXI_in_remaining_weight = 1;
  protected int UART_in_remaining_weight = 1;
  protected int UART_out_remaining_weight = 1;
  
  // 令牌环
  protected int token_holder = 0;
  protected string token_holder_name = "";
  
  // 统计信息
  protected int total_grants = 0;
  protected int grants_per_sequencer[string];
  
  // 同步事件
  protected event sync_event;
  protected int sync_count = 0;
  
  // 是否使能调试
  protected bit debug_enabled = 0;
  
  // ═══════════════════════════════════════════════════════════════
  // 5. 构造函数
  // ═══════════════════════════════════════════════════════════════
  
  function new(string name, uvm_component parent);
    super.new(name, parent);
    // 初始化统计
    grants_per_sequencer["AXI_in_sqr"] = 0;
    grants_per_sequencer["UART_in_sqr"] = 0;
    grants_per_sequencer["UART_out_sqr"] = 0;
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 6. build_phase - 创建子 Sequencer
  // ═══════════════════════════════════════════════════════════════
  
  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    
    `uvm_info(get_name(), "Building uart_env_virtual_sequencer", UVM_LOW)
    
    // 子 Sequencer 通过 config_db 获取，不在这里创建
    // 因为在 env 中已经创建并设置了
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 7. connect_phase - 连接子 Sequencer
  // ═══════════════════════════════════════════════════════════════
  
  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    
    // 从 config_db 获取子 Sequencer 句柄
    if (!uvm_config_db #(uvm_sequencer #(AXI_in_seq_item))::get(
        this, "", "AXI_in_sqr", AXI_in_sqr)) begin
      `uvm_warning(get_name(), $sformatf("AXI_in_sqr not found in config_db"))
    end else begin
      `uvm_info(get_name(), $sformatf("Connected to AXI_in_sqr"), UVM_HIGH)
    end
    if (!uvm_config_db #(uvm_sequencer #(UART_in_seq_item))::get(
        this, "", "UART_in_sqr", UART_in_sqr)) begin
      `uvm_warning(get_name(), $sformatf("UART_in_sqr not found in config_db"))
    end else begin
      `uvm_info(get_name(), $sformatf("Connected to UART_in_sqr"), UVM_HIGH)
    end
    if (!uvm_config_db #(uvm_sequencer #(UART_out_seq_item))::get(
        this, "", "UART_out_sqr", UART_out_sqr)) begin
      `uvm_warning(get_name(), $sformatf("UART_out_sqr not found in config_db"))
    end else begin
      `uvm_info(get_name(), $sformatf("Connected to UART_out_sqr"), UVM_HIGH)
    end
    

  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 8. 仲裁策略设置
  // ═══════════════════════════════════════════════════════════════
  
  // 设置仲裁策略
  function void set_arbitration_policy(arb_policy_e policy);
    arb_policy = policy;
    `uvm_info(get_name(), $sformatf("Arbitration policy set to %s", 
               policy.name()), UVM_MEDIUM)
  endfunction
  
  // 设置优先级
  function void set_AXI_in_priority(int pri);
    AXI_in_priority = pri;
    `uvm_info(get_name(), $sformatf("AXI_in priority set to %0d", pri), UVM_HIGH)
  endfunction
  function void set_UART_in_priority(int pri);
    UART_in_priority = pri;
    `uvm_info(get_name(), $sformatf("UART_in priority set to %0d", pri), UVM_HIGH)
  endfunction
  function void set_UART_out_priority(int pri);
    UART_out_priority = pri;
    `uvm_info(get_name(), $sformatf("UART_out priority set to %0d", pri), UVM_HIGH)
  endfunction
  
  // 设置权重
  function void set_AXI_in_weight(int weight);
    AXI_in_weight = weight;
    reset_weight_counts();
    `uvm_info(get_name(), $sformatf("AXI_in weight set to %0d", weight), UVM_HIGH)
  endfunction
  function void set_UART_in_weight(int weight);
    UART_in_weight = weight;
    reset_weight_counts();
    `uvm_info(get_name(), $sformatf("UART_in weight set to %0d", weight), UVM_HIGH)
  endfunction
  function void set_UART_out_weight(int weight);
    UART_out_weight = weight;
    reset_weight_counts();
    `uvm_info(get_name(), $sformatf("UART_out weight set to %0d", weight), UVM_HIGH)
  endfunction
  
  // 重置权重计数器
  function void reset_weight_counts();
    AXI_in_remaining_weight = AXI_in_weight;
    UART_in_remaining_weight = UART_in_weight;
    UART_out_remaining_weight = UART_out_weight;
  endfunction
  
  // 启用/禁用调试
  function void set_debug(bit enabled);
    debug_enabled = enabled;
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 9. 主仲裁函数 - 选择下一个 Sequencer
  // ═══════════════════════════════════════════════════════════════
  
  virtual function uvm_sequencer_base get_next_sequencer(
      input uvm_sequence_base seq_ptr = null);
    
    uvm_sequencer_base sqrs[$];
    uvm_sequencer_base selected = null;
    
    // 收集有等待序列的 sequencer
    collect_active_sequencers(sqrs);
    
    if (sqrs.size() == 0) begin
      if (debug_enabled)
        `uvm_info(get_name(), "No active sequencers", UVM_HIGH)
      return null;
    end
    
    // 根据策略选择
    case (arb_policy)
      ROUND_ROBIN: begin
        selected = round_robin_select(sqrs);
      end
      PRIORITY_BASED: begin
        selected = priority_select(sqrs);
      end
      WEIGHTED_RR: begin
        selected = weighted_round_robin_select(sqrs);
      end
      TOKEN_RING: begin
        selected = token_ring_select(sqrs);
      end
      SEQUENTIAL: begin
        selected = sequential_select(sqrs);
      end
      USER_DEFINED: begin
        selected = user_defined_select(sqrs);
      end
      default: begin
        selected = sqrs[0];
      end
    endcase
    
    // 统计
    if (selected != null) begin
      string sqr_name = selected.get_name();
      total_grants++;
      if (grants_per_sequencer.exists(sqr_name))
        grants_per_sequencer[sqr_name]++;
      else
        grants_per_sequencer[sqr_name] = 1;
        
      if (debug_enabled)
        `uvm_info(get_name(), $sformatf("Selected: %s, total grants: %0d", 
                   sqr_name, total_grants), UVM_HIGH)
    end
    
    return selected;
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 10. 收集活跃的 Sequencer
  // ═══════════════════════════════════════════════════════════════
  
  protected function void collect_active_sequencers(
      ref uvm_sequencer_base sqrs[$]);
    if (AXI_in_sqr != null && has_sequence(AXI_in_sqr)) begin
      sqrs.push_back(AXI_in_sqr);
      if (debug_enabled)
        `uvm_info(get_name(), "AXI_in_sqr has sequence", UVM_HIGH)
    end
    if (UART_in_sqr != null && has_sequence(UART_in_sqr)) begin
      sqrs.push_back(UART_in_sqr);
      if (debug_enabled)
        `uvm_info(get_name(), "UART_in_sqr has sequence", UVM_HIGH)
    end
    if (UART_out_sqr != null && has_sequence(UART_out_sqr)) begin
      sqrs.push_back(UART_out_sqr);
      if (debug_enabled)
        `uvm_info(get_name(), "UART_out_sqr has sequence", UVM_HIGH)
    end
    

  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 11. 轮询仲裁实现
  // ═══════════════════════════════════════════════════════════════
  
  protected function uvm_sequencer_base round_robin_select(
      ref uvm_sequencer_base sqrs[$]);

    int num_sqrs = sqrs.size();
    int start_idx;
    if (num_sqrs == 0) return null;

    start_idx = round_robin_counter % num_sqrs;
    
    for (int i = 0; i < num_sqrs; i++) begin
      int idx = (start_idx + i) % num_sqrs;
      if (has_sequence(sqrs[idx])) begin
        round_robin_counter = idx + 1;
        return sqrs[idx];
      end
    end
    
    return null;
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 12. 优先级仲裁实现
  // ═══════════════════════════════════════════════════════════════
  
  protected function uvm_sequencer_base priority_select(
      ref uvm_sequencer_base sqrs[$]);
    
    // 构建优先级映射
    typedef struct {
      uvm_sequencer_base sqr;
      int pri;
    } sqr_pri_t;

    sqr_pri_t pri_list[$];
    foreach (sqrs[i]) begin
      if (sqrs[i] == AXI_in_sqr) begin
        sqr_pri_t item;
        item.sqr = sqrs[i];
        item.pri = AXI_in_priority;
        pri_list.push_back(item);
      end
    end
    foreach (sqrs[i]) begin
      if (sqrs[i] == UART_in_sqr) begin
        sqr_pri_t item;
        item.sqr = sqrs[i];
        item.pri = UART_in_priority;
        pri_list.push_back(item);
      end
    end
    foreach (sqrs[i]) begin
      if (sqrs[i] == UART_out_sqr) begin
        sqr_pri_t item;
        item.sqr = sqrs[i];
        item.pri = UART_out_priority;
        pri_list.push_back(item);
      end
    end

    // 按优先级排序（数值小的优先）
    for (int i = 0; i < pri_list.size() - 1; i++) begin
      for (int j = 0; j < pri_list.size() - i - 1; j++) begin
        if (pri_list[j].pri > pri_list[j+1].pri) begin
          sqr_pri_t temp = pri_list[j];
          pri_list[j] = pri_list[j+1];
          pri_list[j+1] = temp;
        end
      end
    end
    
    // 返回最高优先级
    if (pri_list.size() > 0)
      return pri_list[0].sqr;
    
    return null;
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 13. 加权轮询仲裁实现
  // ═══════════════════════════════════════════════════════════════
  
  protected function uvm_sequencer_base weighted_round_robin_select(
      ref uvm_sequencer_base sqrs[$]);
    
    // 检查是否有剩余权重的 sequencer
    if (AXI_in_remaining_weight > 0 && 
        AXI_in_sqr != null && 
        has_sequence(AXI_in_sqr)) begin
      AXI_in_remaining_weight--;
      return AXI_in_sqr;
    end
    if (UART_in_remaining_weight > 0 && 
        UART_in_sqr != null && 
        has_sequence(UART_in_sqr)) begin
      UART_in_remaining_weight--;
      return UART_in_sqr;
    end
    if (UART_out_remaining_weight > 0 && 
        UART_out_sqr != null && 
        has_sequence(UART_out_sqr)) begin
      UART_out_remaining_weight--;
      return UART_out_sqr;
    end
    
    // 所有权重耗尽，重置并重新开始
    reset_weight_counts();
    
    // 递归调用，重新选择
    return weighted_round_robin_select(sqrs);
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 14. 令牌环仲裁实现
  // ═══════════════════════════════════════════════════════════════
  
  protected function uvm_sequencer_base token_ring_select(
      ref uvm_sequencer_base sqrs[$]);
    
    int num_sqrs = sqrs.size();
    if (num_sqrs == 0) return null;
    
    // 确保 token_holder 在有效范围内
    if (token_holder >= num_sqrs)
      token_holder = 0;
    
    // 从当前令牌持有者开始查找
    for (int i = 0; i < num_sqrs; i++) begin
      int idx = (token_holder + i) % num_sqrs;
      if (has_sequence(sqrs[idx])) begin
        token_holder = (idx + 1) % num_sqrs;
        token_holder_name = sqrs[idx].get_name();
        return sqrs[idx];
      end
    end
    
    return null;
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 15. 顺序执行仲裁（非并发）
  // ═══════════════════════════════════════════════════════════════
  
  protected int sequential_index = 0;
  protected uvm_sequencer_base sequential_sqrs[$];
  
  protected function uvm_sequencer_base sequential_select(
      ref uvm_sequencer_base sqrs[$]);

    uvm_sequencer_base selected;
    // 第一次调用时保存顺序
    if (sequential_sqrs.size() == 0) begin
      sequential_sqrs = sqrs;
      sequential_index = 0;
    end

    if (sequential_index >= sequential_sqrs.size()) begin
      // 所有顺序执行完毕，返回 null
      return null;
    end

    selected = sequential_sqrs[sequential_index];

    // 检查该 sequencer 是否还有序列
    if (has_sequence(selected)) begin
      return selected;
    end else begin
      // 当前 sequencer 已完成，移到下一个
      sequential_index++;
      return sequential_select(sqrs);
    end
  endfunction
  
  // 重置顺序执行状态
  function void reset_sequential();
    sequential_sqrs.delete();
    sequential_index = 0;
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 16. 用户自定义仲裁（可重载）
  // ═══════════════════════════════════════════════════════════════
  
  protected function uvm_sequencer_base user_defined_select(
      ref uvm_sequencer_base sqrs[$]);
    
    // 用户可以在子类中重载此函数
    `uvm_warning(get_name(), "USER_DEFINED policy selected but not implemented")
    return sqrs[0];
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 17. 辅助方法
  // ═══════════════════════════════════════════════════════════════
  
  // 检查指定 Sequencer 是否有序列
  function bit has_sequence_on(string sqr_name);
    case (sqr_name)
      "AXI_in": return (AXI_in_sqr != null && has_sequence(AXI_in_sqr));
      "UART_in": return (UART_in_sqr != null && has_sequence(UART_in_sqr));
      "UART_out": return (UART_out_sqr != null && has_sequence(UART_out_sqr));
      default: return 0;
    endcase
  endfunction
  
  // 获取所有活跃 Sequencer 名称
  function string get_active_sequencers_str();
    string str = "";
    if (AXI_in_sqr != null && has_sequence(AXI_in_sqr)) begin
      if (str != "") str = {str, ", "};
      str = {str, "AXI_in"};
    end
    if (UART_in_sqr != null && has_sequence(UART_in_sqr)) begin
      if (str != "") str = {str, ", "};
      str = {str, "UART_in"};
    end
    if (UART_out_sqr != null && has_sequence(UART_out_sqr)) begin
      if (str != "") str = {str, ", "};
      str = {str, "UART_out"};
    end
    return str;
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 18. 同步方法
  // ═══════════════════════════════════════════════════════════════
  
  // 等待所有子 Sequencer 完成
  task wait_for_all_sequencers(int timeout_ms = 1000);
    `uvm_info(get_name(), "Waiting for all sequencers to complete", UVM_MEDIUM)
    
    fork
      begin
        while (get_active_sequencers_str() != "") begin
          #1;
        end
      end
      begin
        #(timeout_ms * 1ms);
        `uvm_error(get_name(), "Timeout waiting for sequencers")
      end
    join_any
    disable fork;
    
    `uvm_info(get_name(), "All sequencers completed", UVM_MEDIUM)
  endtask
  
  // 同步点
  task wait_for_sync(string sync_name = "default", int expected = -1);
    static int sync_count = 0;
    static int expected_count = 0;
    
    if (expected > 0)
      expected_count = expected;
    else
      expected_count++;
    
    sync_count++;
    
    `uvm_info(get_name(), $sformatf("Sync '%s': %0d/%0d", 
               sync_name, sync_count, expected_count), UVM_HIGH)
    
    while (sync_count < expected_count)
      @(sync_event);
    
    -> sync_event;
  endtask
  
  // ═══════════════════════════════════════════════════════════════
  // 19. 统计报告
  // ═══════════════════════════════════════════════════════════════
  
  function void report_arbitration_stats();
    `uvm_info(get_name(), "========================================", UVM_NONE)
    `uvm_info(get_name(), "Arbitration Statistics:", UVM_NONE)
    `uvm_info(get_name(), $sformatf("  Policy: %s", arb_policy.name()), UVM_NONE)
    `uvm_info(get_name(), $sformatf("  Total Grants: %0d", total_grants), UVM_NONE)
    `uvm_info(get_name(), "  Grants per Sequencer:", UVM_NONE)
    
    foreach (grants_per_sequencer[sqr_name]) begin
      `uvm_info(get_name(), $sformatf("    %s: %0d", 
                 sqr_name, grants_per_sequencer[sqr_name]), UVM_NONE)
    end
    
    `uvm_info(get_name(), "========================================", UVM_NONE)
  endfunction
  
  // ═══════════════════════════════════════════════════════════════
  // 20. 运行时相位
  // ═══════════════════════════════════════════════════════════════
  
  virtual task run_phase(uvm_phase phase);
    super.run_phase(phase);
    `uvm_info(get_name(), "Virtual sequencer run phase", UVM_HIGH)
  endtask
  
  virtual function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    report_arbitration_stats();
  endfunction

endclass : uart_env_virtual_sequencer

`endif // UART_ENV_VIRTUAL_SEQUENCER_SV