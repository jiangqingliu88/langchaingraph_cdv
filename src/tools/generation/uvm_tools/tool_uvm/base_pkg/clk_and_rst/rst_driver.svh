// ════════════════════════════════════════════════════════════════
// rst_driver.svh —— 复位驱动器（CLK_RST_NUM_RSTS 个并发复位通道）
// 职责: 上电复位时序、issue_reset 动态复位请求（请求队列 + 完成握手）
// 依赖: clk_rst_config.svh, clk_rst_if.svh
// ════════════════════════════════════════════════════════════════

`ifndef RST_DRIVER_SVH
`define RST_DRIVER_SVH

// ── 5. Reset Driver ──
class rst_driver extends uvm_driver #(uvm_sequence_item);
  `uvm_component_utils(rst_driver)
  virtual clk_rst_if vif;
  clk_rst_config     cfg;

  typedef struct { int assert_cycles; int recover_cycles; } rst_req_t;
  rst_req_t rst_req_queue[`CLK_RST_NUM_RSTS][$];

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(clk_rst_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Reset config not set")
    if (!uvm_config_db #(virtual clk_rst_if)::get(this, "", "vif", vif))
      `uvm_fatal("VIF", "Reset interface not set")
  endfunction

  virtual task wait_clock_cycles(int clk_idx, int cycles);
    repeat(cycles) @(posedge vif.clk[clk_idx]);
  endtask

  virtual task drive_reset(int idx);
    bit active_val  = cfg.rst_active_low ? 1'b0 : 1'b1;
    bit inactive_val = cfg.rst_active_low ? 1'b1 : 1'b0;
    vif.rst_n[idx] = cfg.rst_start_value ? inactive_val : active_val;
    vif.rst_active[idx] = (vif.rst_n[idx] == active_val);
    if (cfg.rst_start_value == 0) begin
      wait_clock_cycles(idx, cfg.rst_assert_cycles);
      vif.rst_n[idx] = inactive_val;
      vif.rst_active[idx] = 0;
      wait_clock_cycles(idx, cfg.rst_recover_cycles);
    end
    forever begin
      @(vif.cb);
      if (rst_req_queue[idx].size() > 0) begin
        rst_req_t req = rst_req_queue[idx].pop_front();
        vif.rst_n[idx] = active_val;
        vif.rst_active[idx] = 1;
        wait_clock_cycles(idx, req.assert_cycles);
        vif.rst_n[idx] = inactive_val;
        vif.rst_active[idx] = 0;
        wait_clock_cycles(idx, req.recover_cycles);
      end
    end
  endtask

  virtual task issue_reset(int idx, int assert_cycles = 10, int recover_cycles = 5);
    rst_req_t req;
    req.assert_cycles  = assert_cycles;
    req.recover_cycles = recover_cycles;
    rst_req_queue[idx].push_back(req);
    @(negedge vif.rst_active[idx]);
  endtask

  task run_phase(uvm_phase phase);
    fork
      for (int i = 0; i < `CLK_RST_NUM_RSTS; i++) drive_reset(i);
    join
  endtask
endclass : rst_driver

`endif // RST_DRIVER_SVH
