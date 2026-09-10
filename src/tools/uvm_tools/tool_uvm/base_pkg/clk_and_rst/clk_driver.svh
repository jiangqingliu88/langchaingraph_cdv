// ════════════════════════════════════════════════════════════════
// clk_driver.svh —— 时钟驱动器（CLK_RST_NUM_CLKS 个并发时钟）
// 职责: 周期/占空比/抖动驱动、clk_gate 门控握手、clk_stop_after 限拍停止
// 依赖: clk_rst_config.svh, clk_rst_if.svh
// ════════════════════════════════════════════════════════════════

`ifndef CLK_DRIVER_SVH
`define CLK_DRIVER_SVH

// ── 4. Clock Driver ──
class clk_driver extends uvm_driver #(uvm_sequence_item);
  `uvm_component_utils(clk_driver)
  virtual clk_rst_if vif;
  clk_rst_config     cfg;
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(clk_rst_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Clock config not set")
    if (!uvm_config_db #(virtual clk_rst_if)::get(this, "", "vif", vif))
      `uvm_fatal("VIF", "Clock interface not set")
  endfunction
  task run_phase(uvm_phase phase);
    fork
      for (int i = 0; i < `CLK_RST_NUM_CLKS; i++) drive_clock(i);
      if (cfg.enable_clock_gating) drive_clock_gating();
    join
  endtask
  virtual task drive_clock(int idx);
    real half_hi = cfg.clk_period_ps * cfg.clk_duty_cycle / 100;
    real half_lo = cfg.clk_period_ps * (100 - cfg.clk_duty_cycle) / 100;
    int cycles = 0;
    vif.clk[idx] = cfg.clk_start_value;
    vif.clk_running[idx] = 1;
    forever begin
      #(half_hi * 1ps);
      if (cfg.clk_jitter_ps > 0) #($urandom_range(0, cfg.clk_jitter_ps) * 1ps);
      vif.clk[idx] = 1'b1;
      #(half_lo * 1ps);
      if (cfg.clk_jitter_ps > 0) #($urandom_range(0, cfg.clk_jitter_ps) * 1ps);
      vif.clk[idx] = 1'b0;
      cycles++;
      if (vif.clk_gate[idx]) begin
        vif.clk_running[idx] = 0;
        @(negedge vif.clk_gate[idx]);
        vif.clk_running[idx] = 1;
      end
      if (cfg.clk_stop_after > 0 && cycles >= cfg.clk_stop_after) begin
        vif.clk_running[idx] = 0;
        break;
      end
    end
  endtask
  virtual task drive_clock_gating();
    forever begin
      #(cfg.clock_gate_cycles * cfg.clk_period_ps * 1ps);
      vif.clk_gate[0] = 1'b1;
      #(cfg.clock_ungate_cycles * cfg.clk_period_ps * 1ps);
      vif.clk_gate[0] = 1'b0;
    end
  endtask
endclass : clk_driver

`endif // CLK_DRIVER_SVH
