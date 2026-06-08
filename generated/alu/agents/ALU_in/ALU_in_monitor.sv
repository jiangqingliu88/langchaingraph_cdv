// ============================================================
// Monitor Callback
// ============================================================

typedef class ALU_in_monitor;

class ALU_in_monitor_callback extends uvm_callback;
  `uvm_object_utils(ALU_in_monitor_callback)

  function new(string name = "ALU_in_monitor_callback");
    super.new(name);
  endfunction

  // 采样前
  virtual function void on_pre_sample(
    ALU_in_monitor monitor,
    virtual ALU_in_interface vif
  );
  endfunction

  // 采样后（可修改 item）
  virtual function void on_post_sample(
    ALU_in_monitor monitor,
    ALU_in_seq_item item
  );
  endfunction

  // write 前
  virtual function void on_pre_write(
    ALU_in_monitor monitor,
    ALU_in_seq_item item
  );
  endfunction

  // write 后
  virtual function void on_post_write(
    ALU_in_monitor monitor,
    ALU_in_seq_item item
  );
  endfunction

endclass : ALU_in_monitor_callback

// ============================================================
// Monitor: ALU_in_monitor
// 场景: 采样/过滤/XZ检测/带宽监控/回调/统计
// ============================================================

class ALU_in_monitor extends uvm_monitor;
  `uvm_component_utils(ALU_in_monitor)
  `uvm_register_cb(ALU_in_monitor, ALU_in_monitor_callback)

  uvm_analysis_port #(ALU_in_seq_item) item_collected_port;
  virtual ALU_in_interface vif;
  ALU_in_config cfg;

  // ─── 统计 ───
  protected int m_collected    = 0;
  protected int m_filtered_out = 0;
  protected int m_xz_detected  = 0;
  protected realtime m_last_time = 0;
  protected realtime m_total_bw = 0;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    item_collected_port = new("item_collected_port", this);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(ALU_in_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Config not set")
    if (!uvm_config_db #(virtual ALU_in_interface)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Virtual interface not set")
  endfunction

  task run_phase(uvm_phase phase);
    forever begin
      ALU_in_seq_item item;

      @(vif.cb);
      `uvm_do_callbacks(ALU_in_monitor, ALU_in_monitor_callback,
                        on_pre_sample(this, vif))

      // X/Z 检测 — skip first cycle after reset
      if (cfg.check_xz && is_xz_detected() && m_collected > 0) begin
        m_xz_detected++;
        `uvm_warning("MON", "X/Z detected on interface")
      end

      item = ALU_in_seq_item::type_id::create("item");
      sample_transaction(item);

      // 过滤
      if (cfg.filter_enabled && !filter_transaction(item)) begin
        m_filtered_out++;
        continue;
      end

      `uvm_do_callbacks(ALU_in_monitor, ALU_in_monitor_callback,
                        on_post_sample(this, item))

      `uvm_do_callbacks(ALU_in_monitor, ALU_in_monitor_callback,
                        on_pre_write(this, item))

      item_collected_port.write(item);
      m_collected++;

      // 带宽统计
      update_bandwidth();

      `uvm_do_callbacks(ALU_in_monitor, ALU_in_monitor_callback,
                        on_post_write(this, item))
    end
  endtask

  virtual function void sample_transaction(ALU_in_seq_item item);
    item.ready = vif.cb.ready;
    item.result = vif.cb.result;
  endfunction

  // ─── X/Z 检测 ───
  virtual function bit is_xz_detected();
    if ($isunknown(vif.a)) return 1;
    if ($isunknown(vif.b)) return 1;
    if ($isunknown(vif.op)) return 1;
    if ($isunknown(vif.valid)) return 1;
    if ($isunknown(vif.cb.ready)) return 1;
    if ($isunknown(vif.cb.result)) return 1;
    return 0;
  endfunction

  // ─── 过滤 ───
  virtual function bit filter_transaction(ALU_in_seq_item item);
    return 1;  // 默认全部通过
  endfunction

  // ─── 带宽监控 ───
  virtual function void update_bandwidth();
    realtime now = $realtime;
    if (m_last_time > 0) begin
      m_total_bw += (now - m_last_time);
    end
    m_last_time = now;
  endfunction

  virtual function real get_bandwidth_bps();
    if (m_collected == 0) return 0;
    return (m_collected * 8) / (m_total_bw / 1e9);
  endfunction

  virtual function void report_phase(uvm_phase phase);
    `uvm_info("MON", $sformatf(
      "Monitor %s: collected=%0d filtered=%0d xz=%0d bw=%.1f Gbps",
      get_full_name(), m_collected, m_filtered_out, m_xz_detected,
      get_bandwidth_bps()), UVM_NONE)
  endfunction

endclass : ALU_in_monitor