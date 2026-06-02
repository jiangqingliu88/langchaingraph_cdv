
// ============================================================
// Sequencer Callback
// ============================================================

typedef class UART_in_sequencer;
typedef class UART_in_base_seq;

class UART_in_sequencer_callback extends uvm_callback;
  `uvm_object_utils(UART_in_sequencer_callback)

  function new(string name = "UART_in_sequencer_callback");
    super.new(name);
  endfunction

  virtual function void on_pre_arbitration(
    UART_in_sequencer sequencer
  );
  endfunction

  virtual function void on_post_arbitration(
    UART_in_sequencer sequencer,
    uvm_sequence_base granted_seq
  );
  endfunction

  virtual function void on_sequence_start(
    UART_in_sequencer sequencer,
    uvm_sequence_base seq
  );
  endfunction

  virtual function void on_sequence_end(
    UART_in_sequencer sequencer,
    uvm_sequence_base seq
  );
  endfunction

  virtual function void on_response_received(
    UART_in_sequencer sequencer,
    UART_in_seq_item response
  );
  endfunction

endclass : UART_in_sequencer_callback

// ============================================================
// Sequencer: UART_in_sequencer
// 场景: 仲裁/响应/限速/回调/统计/Grab-Lock/超时
// ============================================================

class UART_in_sequencer extends uvm_sequencer #(UART_in_seq_item);
  `uvm_component_utils(UART_in_sequencer)
  `uvm_register_cb(UART_in_sequencer, UART_in_sequencer_callback)

  UART_in_config cfg;

  // ─── 响应队列 ───
  protected UART_in_seq_item rsp_queue[$];
  protected UART_in_seq_item req_table[int];
  protected realtime rsp_timeout_ns = 10000;

  // ─── Grab/Lock ───
  protected uvm_sequence_base m_grabber;
  protected uvm_sequence_base arb_sequence_queue[$];

  // ─── 统计 ───
  protected int m_req_cnt    = 0;
  protected int m_rsp_cnt    = 0;
  protected int m_grant_cnt  = 0;
  protected int m_req_id     = 0;
  protected int m_seq_started = 0;
  protected int m_seq_ended   = 0;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(UART_in_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Config not set")
  endfunction

  // ═══════════════════════════════════════════
  // 仲裁
  // ═══════════════════════════════════════════

  virtual function uvm_sequence_base get_next_sequence();
    uvm_sequence_base seq;

    `uvm_do_callbacks(UART_in_sequencer, UART_in_sequencer_callback,
                      on_pre_arbitration(this))

    if (m_grabber != null) begin
      seq = m_grabber;
      m_grabber = null;
    end
    else begin
      seq = user_arbitration();
    end
    if (seq == null) seq = null;

    m_grant_cnt++;
    `uvm_do_callbacks(UART_in_sequencer, UART_in_sequencer_callback,
                      on_post_arbitration(this, seq))
    return seq;
  endfunction

  virtual function uvm_sequence_base user_arbitration();
    if (cfg.arbitration_mode == 1) return priority_arbitration();
    if (cfg.arbitration_mode == 2) return round_robin_arbitration();
    return null;
  endfunction

  virtual function uvm_sequence_base priority_arbitration();
    uvm_sequence_base best = null;
    int best_pri = 999;
    foreach (arb_sequence_queue[i]) begin
      UART_in_base_seq seq;
      if ($cast(seq, arb_sequence_queue[i])) begin
        if (seq.get_priority() < best_pri) begin
          best_pri = seq.get_priority();
          best = seq;
        end
      end
    end
    if (best != null) begin
      int _idx;
      for (int _j = 0; _j < arb_sequence_queue.size(); _j++)
        if (arb_sequence_queue[_j] == best) begin _idx = _j; break; end
      arb_sequence_queue.delete(_idx);
    end
    return best;
  endfunction

  protected int m_rr_idx = 0;
  virtual function uvm_sequence_base round_robin_arbitration();
    if (arb_sequence_queue.size() == 0) return null;
    m_rr_idx = (m_rr_idx + 1) % arb_sequence_queue.size();
    return arb_sequence_queue[m_rr_idx];
  endfunction

  // ─── Grab/Lock ───
  virtual task grab(uvm_sequence_base sequence_ptr);
    if (m_grabber == null) m_grabber = sequence_ptr;
  endtask

  virtual function void ungrab(uvm_sequence_base sequence_ptr);
    if (m_grabber == sequence_ptr) m_grabber = null;
  endfunction

  // ═══════════════════════════════════════════
  // Sequence 管理
  // ═══════════════════════════════════════════

  virtual task start_sequence(uvm_sequence_base seq, int timeout_ns = 0);
    m_seq_started++;
    `uvm_do_callbacks(UART_in_sequencer, UART_in_sequencer_callback,
                      on_sequence_start(this, seq))
    if (timeout_ns > 0) begin
      fork
        begin
          seq.start(this);
        end
        begin
          #(timeout_ns * 1ns);
          if (seq.get_sequence_state() != UVM_FINISHED) begin
            `uvm_warning("SEQ", "Sequence timeout, killing")
            seq.kill();
          end
        end
      join_any
      disable fork;
    end
    else begin
      seq.start(this);
    end
    m_seq_ended++;
    `uvm_do_callbacks(UART_in_sequencer, UART_in_sequencer_callback,
                      on_sequence_end(this, seq))
  endtask

  virtual function void stop_all_sequences();
    foreach (arb_sequence_queue[i]) arb_sequence_queue[i].kill();
  endfunction

  virtual function void set_default_sequence(string type_name);
    uvm_factory f = uvm_factory::get();
    uvm_sequence_base _seq;
    if ($cast(_seq, f.create_object_by_name(type_name)))
      arb_sequence_queue.push_back(_seq);
  endfunction

  // ═══════════════════════════════════════════
  // 响应处理（异步+乱序+超时）
  // ═══════════════════════════════════════════

  virtual function void put_response(uvm_sequence_item rsp);
    UART_in_seq_item item;
    if (!$cast(item, rsp)) begin
      `uvm_error("SEQ", "Response type mismatch")
      return;
    end

    rsp_queue.push_back(item);
    m_rsp_cnt++;

    `uvm_do_callbacks(UART_in_sequencer, UART_in_sequencer_callback,
                      on_response_received(this, item))

    super.put_response(rsp);
  endfunction

  virtual task get_response_timeout(output UART_in_seq_item rsp,
                                    input realtime timeout_ns = 0,
                                    output bit success);
    realtime t = (timeout_ns > 0) ? timeout_ns : rsp_timeout_ns;
    fork
      begin
        wait(rsp_queue.size() > 0);
        rsp = rsp_queue.pop_front();
        success = 1;
      end
      begin
        #(t * 1ns);
        success = 0;
      end
    join_any
    disable fork;
    if (!success) `uvm_warning("SEQ", "get_response timeout")
  endtask

  virtual function int allocate_req_id();
    return m_req_id++;
  endfunction

  virtual function void store_request(int id, UART_in_seq_item req);
    req_table[id] = req;
  endfunction

  virtual function UART_in_seq_item get_request_by_id(int id);
    if (req_table.exists(id)) begin
      UART_in_seq_item req = req_table[id];
      req_table.delete(id);
      return req;
    end
    return null;
  endfunction

  // ═══════════════════════════════════════════
  // 流量控制
  // ═══════════════════════════════════════════

  virtual task throttle();
    if (cfg.max_pending > 0 && (m_req_cnt - m_rsp_cnt) >= cfg.max_pending)
      wait((m_req_cnt - m_rsp_cnt) < cfg.max_pending);
  endtask

  virtual task throttle_by_interval();
    if (cfg.min_interval_ns > 0) begin
      static realtime last_time = 0;
      realtime now = $realtime;
      realtime elapsed = now - last_time;
      if (elapsed < cfg.min_interval_ns) #(cfg.min_interval_ns - elapsed);
      last_time = $realtime;
    end
  endtask

  // ═══════════════════════════════════════════
  // 统计
  // ═══════════════════════════════════════════

  virtual function void inc_req(); m_req_cnt++; endfunction
  virtual function int  pending(); return m_req_cnt - m_rsp_cnt; endfunction

  virtual function void get_statistics(output int reqs, output int rsps,
                                       output int granted, output int pending_cnt,
                                       output int seq_started, output int seq_ended);
    reqs        = m_req_cnt;
    rsps        = m_rsp_cnt;
    granted     = m_grant_cnt;
    pending_cnt = pending();
    seq_started = m_seq_started;
    seq_ended   = m_seq_ended;
  endfunction

  virtual function void report_phase(uvm_phase phase);
    int reqs, rsps, granted, pending_cnt, started, ended;
    super.report_phase(phase);
    get_statistics(reqs, rsps, granted, pending_cnt, started, ended);
    `uvm_info("SEQ", $sformatf(
      "Sequencer %s: reqs=%0d rsps=%0d granted=%0d pending=%0d seqs=%0d/%0d",
      get_full_name(), reqs, rsps, granted, pending_cnt, started, ended), UVM_NONE)
  endfunction

endclass : UART_in_sequencer


