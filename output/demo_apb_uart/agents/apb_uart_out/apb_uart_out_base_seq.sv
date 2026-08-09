// ============================================================
// Agent Base Sequence: apb_uart_out_base_seq
// 完整企业级模板 - 覆盖所有扩展场景
// ============================================================

class apb_uart_out_base_seq extends uvm_sequence #(apb_uart_out_seq_item);
  `uvm_object_utils(apb_uart_out_base_seq)
  `uvm_declare_p_sequencer(apb_uart_out_sequencer)

  // ─── Sequence 属性 ───
  protected int  m_priority     = 100;
  protected bit  m_stop_request = 0;
  protected realtime m_timeout_ns = 0;
  protected int  m_max_retries  = 3;

  function new(string name = "apb_uart_out_base_seq");
    super.new(name);
  endfunction

  // ═══════════════════════════════════════════
  // 生命周期
  // ═══════════════════════════════════════════

  virtual task pre_start();
    super.pre_start();
    `uvm_info("SEQ_LIFE", $sformatf("[%s] pre_start", get_name()), UVM_HIGH)
  endtask

  virtual task pre_body();
    `uvm_info("SEQ_LIFE", $sformatf("[%s] pre_body", get_name()), UVM_HIGH)
  endtask

  virtual task body();
    `uvm_info("SEQ", $sformatf("[%s] body - override in derived", get_name()), UVM_MEDIUM)
  endtask

  virtual task post_body();
    `uvm_info("SEQ_LIFE", $sformatf("[%s] post_body", get_name()), UVM_HIGH)
  endtask

  virtual task post_start();
    super.post_start();
    `uvm_info("SEQ_LIFE", $sformatf("[%s] post_start", get_name()), UVM_HIGH)
  endtask

  // ═══════════════════════════════════════════
  // 优先级管理
  // ═══════════════════════════════════════════

  virtual function void set_priority(int pri);
    m_priority = pri;
  endfunction

  virtual function int get_priority();
    return m_priority;
  endfunction

  // ═══════════════════════════════════════════
  // Grab / Lock
  // ═══════════════════════════════════════════

  virtual task grab_sequencer();
    p_sequencer.grab(this);
    `uvm_info("SEQ", $sformatf("[%s] Grabbed sequencer", get_name()), UVM_MEDIUM)
  endtask

  virtual task ungrab_sequencer();
    p_sequencer.ungrab(this);
    `uvm_info("SEQ", $sformatf("[%s] Ungrabbed sequencer", get_name()), UVM_MEDIUM)
  endtask

  virtual task lock_sequencer();
    p_sequencer.lock(this);
    `uvm_info("SEQ", $sformatf("[%s] Locked sequencer", get_name()), UVM_MEDIUM)
  endtask

  virtual task unlock_sequencer();
    p_sequencer.unlock(this);
    `uvm_info("SEQ", $sformatf("[%s] Unlocked sequencer", get_name()), UVM_MEDIUM)
  endtask

  // ═══════════════════════════════════════════
  // 发送事务（基础 + 高级）
  // ═══════════════════════════════════════════

  // 基础发送
  protected task send_transaction(apb_uart_out_seq_item req);
    `uvm_info("SEQ_SEND", $sformatf("Sending:\n%s", req.sprint()), UVM_HIGH)
    start_item(req);
    // Item already randomized by create_random_transaction
    // Re-randomization after start_item races with driver reading values
    finish_item(req);
    p_sequencer.inc_req();
  endtask

  // 带超时的发送
  protected task send_transaction_timeout(apb_uart_out_seq_item req,
                                          input realtime timeout_ns = 0,
                                          output bit success);
    realtime t = (timeout_ns > 0) ? timeout_ns : m_timeout_ns;
    fork
      begin
        send_transaction(req);
        success = 1;
      end
      begin
        if (t > 0) begin
          #(t * 1ns);
          `uvm_warning("SEQ_TO", "send_transaction timeout")
        end
        success = 0;
      end
    join_any
    disable fork;
  endtask

  // 带约束的发送
  protected task send_transaction_with(apb_uart_out_seq_item req);
    start_item(req);
    if (!req.randomize() with {})
      `uvm_error("SEQ", "randomize with constraints failed")
    finish_item(req);
    p_sequencer.inc_req();
  endtask

  // 创建随机事务
  protected function apb_uart_out_seq_item create_random_transaction(string name = "req");
    apb_uart_out_seq_item req;
    req = apb_uart_out_seq_item::type_id::create(name);
    if (!req.randomize()) begin
      `uvm_error("SEQ", "Randomization failed")
      req = null;
    end
    return req;
  endfunction

  // 发送 N 个随机事务
  protected task send_random_transactions(int count = 10);
    `uvm_info("SEQ", $sformatf("Sending %0d random transactions", count), UVM_MEDIUM)
    repeat(count) begin
      apb_uart_out_seq_item req = create_random_transaction();
      if (req != null) send_transaction(req);
      if (m_stop_request) break;
    end
  endtask

  // ═══════════════════════════════════════════
  // 响应处理
  // ═══════════════════════════════════════════

  protected task send_and_get_response(apb_uart_out_seq_item req,
                                       output apb_uart_out_seq_item rsp,
                                       input realtime timeout_ns = 0,
                                       output bit success);
    send_transaction(req);
    p_sequencer.get_response_timeout(rsp, timeout_ns, success);
    `uvm_info("SEQ_RSP", $sformatf("Got response: %s", rsp.convert2string()), UVM_HIGH)
  endtask

  protected task send_request_with_retry(apb_uart_out_seq_item req,
                                         input int max_retries = 3);
    int retries = 0;
    bit success = 0;
    apb_uart_out_seq_item rsp;

    while (retries < max_retries && !success) begin
      send_and_get_response(req, rsp, m_timeout_ns, success);
      if (!success || rsp.error) begin
        retries++;
        `uvm_warning("SEQ_RETRY", $sformatf("Retry %0d/%0d", retries, max_retries))
      end
    end
    if (retries >= max_retries && !success)
      `uvm_error("SEQ_RETRY", "Max retries reached")
  endtask

  // ═══════════════════════════════════════════
  // 同步机制
  // ═══════════════════════════════════════════

  // 等待事件
  protected task wait_for_event(event evt, input realtime timeout_ns = 0);
    if (timeout_ns > 0) begin
      fork
        @(evt);
        #(timeout_ns * 1ns);
      join_any
      disable fork;
    end
    else begin
      @(evt);
    end
  endtask

  // 等待条件
  protected task wait_for_condition(ref bit condition, input realtime timeout_ns = 0);
    realtime start = $realtime;
    while (!condition) begin
      #1;
      if (timeout_ns > 0 && ($realtime - start) > timeout_ns) begin
        `uvm_warning("SEQ_WAIT", "Condition timeout")
        break;
      end
    end
  endtask

  // 同步点（多个 Sequence 汇合）
  protected task sync_point(string name, int num_participants);
    static event sync_events[string];
    static int  sync_count[string];

    if (!sync_events.exists(name)) begin
      event _e;
      sync_events[name] = _e;
      sync_count[name] = 0;
    end

    sync_count[name]++;
    `uvm_info("SEQ_SYNC", $sformatf("[%s] Sync point '%s': %0d/%0d arrived",
               get_name(), name, sync_count[name], num_participants), UVM_MEDIUM)

    if (sync_count[name] == num_participants) begin
      ->sync_events[name];
      sync_count[name] = 0;
    end
    else begin
      @(sync_events[name]);
    end
  endtask

  // ═══════════════════════════════════════════
  // 流程控制
  // ═══════════════════════════════════════════

  virtual function void stop();
    m_stop_request = 1;
  endfunction

  virtual function bit is_stopped();
    return m_stop_request;
  endfunction

  virtual function void set_timeout(realtime timeout_ns);
    m_timeout_ns = timeout_ns;
  endfunction

  // ═══════════════════════════════════════════
  // 延迟与等待
  // ═══════════════════════════════════════════

  protected task wait_cycles(int cycles = 1);
    repeat(cycles) #1;
  endtask

  protected task random_delay(int min_cycles = 0, int max_cycles = 10);
    int delay = $urandom_range(min_cycles, max_cycles);
    if (delay > 0) wait_cycles(delay);
  endtask

  // ═══════════════════════════════════════════
  // 错误处理
  // ═══════════════════════════════════════════

  protected function void handle_randomize_failure(apb_uart_out_seq_item req,
                                                    string ctx = "");
    if (p_sequencer.cfg.fatal_on_rand_fail) begin
      `uvm_fatal("SEQ_RAND", $sformatf("[%s] Randomization failed: %s",
                 ctx, req.get_name()))
    end
    else begin
      `uvm_error("SEQ_RAND", $sformatf("[%s] Randomization failed: %s",
                 ctx, req.get_name()))
    end
  endfunction

  // ═══════════════════════════════════════════
  // 统计
  // ═══════════════════════════════════════════

  virtual function string get_statistics();
    return $sformatf("Sequence %s: priority=%0d timeout=%0tns",
                     get_name(), m_priority, m_timeout_ns);
  endfunction

endclass : apb_uart_out_base_seq


// ============================================================
// Random Sequence: apb_uart_out_random_seq
// 场景: 随机事务/动态约束/流量控制
// ============================================================

class apb_uart_out_random_seq extends apb_uart_out_base_seq;
  `uvm_object_utils(apb_uart_out_random_seq)

  rand int num_transactions = 10;
  rand int delay_min        = 0;
  rand int delay_max        = 5;

  constraint c_num_valid   { num_transactions inside {[1:1000]}; }
  constraint c_delay_valid { delay_min <= delay_max; delay_max <= 100; }

  function new(string name = "apb_uart_out_random_seq");
    super.new(name);
  endfunction

  virtual task body();
    apb_uart_out_seq_item req;

    `uvm_info("SEQ", $sformatf("Random seq: count=%0d delay=[%0d:%0d]",
               num_transactions, delay_min, delay_max), UVM_MEDIUM)

    repeat(num_transactions) begin
      if (m_stop_request) break;

      random_delay(delay_min, delay_max);

      req = create_random_transaction();
      if (req != null) send_transaction(req);
    end

    `uvm_info("SEQ", "Random seq completed", UVM_MEDIUM)
  endtask

endclass : apb_uart_out_random_seq


// ============================================================
// Directed Sequence: apb_uart_out_directed_seq
// 场景: 定向测试/特定场景/可配置操作序列
// ============================================================

class apb_uart_out_directed_seq extends apb_uart_out_base_seq;
  `uvm_object_utils(apb_uart_out_directed_seq)
  bit [DATA_WIDTH-1:0] data = 0;

  function new(string name = "apb_uart_out_directed_seq");
    super.new(name);
  endfunction

  virtual task body();
    apb_uart_out_seq_item req;

    `uvm_info("SEQ", "Directed seq", UVM_MEDIUM)

    req = apb_uart_out_seq_item::type_id::create("req");
    start_item(req);
    req.data = data;
    finish_item(req);
    p_sequencer.inc_req();

    `uvm_info("SEQ", "Directed seq completed", UVM_MEDIUM)
  endtask

endclass : apb_uart_out_directed_seq


// ============================================================
// Register Sequence: apb_uart_out_reg_seq
// 场景: 寄存器读写/带响应的操作
// ============================================================

class apb_uart_out_reg_seq extends apb_uart_out_base_seq;
  `uvm_object_utils(apb_uart_out_reg_seq)

  rand bit [7:0]  reg_addr;
  rand bit [7:0]  reg_data;
  rand bit        is_write;

  function new(string name = "apb_uart_out_reg_seq");
    super.new(name);
  endfunction

  virtual task body();
    apb_uart_out_seq_item req, rsp;
    bit success;

    // 写寄存器
    req = apb_uart_out_seq_item::type_id::create("req");
    start_item(req);
    //req.randomize() with { addr == reg_addr; data == reg_data; is_write == 1; };
    finish_item(req);
    p_sequencer.inc_req();

    // 读寄存器（带响应）
    req = apb_uart_out_seq_item::type_id::create("req");
    send_and_get_response(req, rsp, m_timeout_ns, success);
    if (success)
      `uvm_info("REG", $sformatf("Read response: %s", rsp.convert2string()), UVM_NONE)
      // `uvm_info("REG", $sformatf("Read 0x%0h = 0x%0h", reg_addr, rsp.rdata), UVM_NONE) -- rdata 字段待定义
    else
      `uvm_error("REG", "Read timeout")
  endtask

endclass : apb_uart_out_reg_seq


// ============================================================
// Stress Sequence: apb_uart_out_stress_seq
// 场景: 压力测试/最大吞吐/背靠背
// ============================================================

class apb_uart_out_stress_seq extends apb_uart_out_base_seq;
  `uvm_object_utils(apb_uart_out_stress_seq)

  rand int burst_size      = 100;
  rand int burst_count     = 10;
  rand int idle_cycles     = 0;

  constraint c_burst { burst_size inside {[10:1000]}; }

  function new(string name = "apb_uart_out_stress_seq");
    super.new(name);
    m_priority = 50;  // 高优先级
  endfunction

  virtual task body();
    `uvm_info("STRESS", $sformatf("Stress: bursts=%0d size=%0d", burst_count, burst_size), UVM_NONE)

    repeat(burst_count) begin
      if (m_stop_request) break;

      // 背靠背发送
      repeat(burst_size) begin
        apb_uart_out_seq_item req = create_random_transaction();
        if (req != null) send_transaction(req);
      end

      // 突发间隔
      if (idle_cycles > 0) wait_cycles(idle_cycles);
    end

    `uvm_info("STRESS", "Stress seq completed", UVM_NONE)
  endtask

endclass : apb_uart_out_stress_seq


// ============================================================
// Error Injection Sequence: apb_uart_out_error_seq
// 场景: 错误注入/异常测试
// ============================================================

class apb_uart_out_error_seq extends apb_uart_out_base_seq;
  `uvm_object_utils(apb_uart_out_error_seq)

  rand int error_rate = 10;  // 10% 错误率
  rand int error_type = 0;

  function new(string name = "apb_uart_out_error_seq");
    super.new(name);
  endfunction

  virtual task body();
    `uvm_info("ERR", $sformatf("Error injection: rate=%0d%%", error_rate), UVM_MEDIUM)

    repeat(100) begin
      apb_uart_out_seq_item req = create_random_transaction();
      if (req == null) continue;

      // 注入错误
      //if (($urandom_range(0, 99) < error_rate)) begin
      //  case(error_type)
      //    0: req.op = req.op ^ 3'b111;
      //    1: req.a  = ~req.a;
      //    2: req.b  = ~req.b;
      //  endcase
      //  `uvm_info("ERR_INJ", "Injected error", UVM_HIGH)
      //end

      send_transaction(req);
    end
  endtask

endclass : apb_uart_out_error_seq
//=======================================================================================
/*
*class my_seq extends uvm_sequence #(my_item);
*    
*    task body();
*        // ═══ Lock: 排队等，拿到后独占 ═══
*        lock_sequencer();  // 如果别的 Sequence 占着，这里阻塞等待
*        
*        // 这段时间只有我能发 item
*        repeat(10) `uvm_do(req)
*        
*        unlock_sequencer();  // 释放，别人可以用了
*        
*        
*        // ═══ Grab: 立刻抢过来 ═══
*        grab_sequencer();  // 不管谁在用，立刻抢过来
*        
*        // 紧急操作
*        send_reset_sequence();
*        
*        ungrab_sequencer();  // 归还
*    endtask
*endclass
*/