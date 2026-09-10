// ════════════════════════════════════════════════════════════════
// clk_rst_monitor.svh —— 时钟复位监视器
// 职责: 采样时钟上升沿（周期测量）与复位断言/解断言，
//   经 event_port 广播 clk_rst_event；report_phase 输出边沿/周期统计
// 依赖: clk_rst_config.svh, clk_rst_if.svh, clk_rst_event.svh
// ════════════════════════════════════════════════════════════════

`ifndef CLK_RST_MONITOR_SVH
`define CLK_RST_MONITOR_SVH

// ── 6. Monitor ──
class clk_rst_monitor extends uvm_monitor;
  `uvm_component_utils(clk_rst_monitor)
  virtual clk_rst_if vif;
  clk_rst_config     cfg;
  protected realtime m_clk_period_measured[`CLK_RST_NUM_CLKS];
  protected int      m_clk_count[`CLK_RST_NUM_CLKS];
  protected int      m_rst_count[`CLK_RST_NUM_RSTS];
  protected realtime m_last_posedge[`CLK_RST_NUM_CLKS];
  uvm_analysis_port #(clk_rst_event) event_port;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    event_port = new("event_port", this);
  endfunction
  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(clk_rst_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Config not set")
    if (!uvm_config_db #(virtual clk_rst_if)::get(this, "", "vif", vif))
      `uvm_fatal("VIF", "Interface not set")
  endfunction
  task run_phase(uvm_phase phase);
    fork
      for (int i = 0; i < `CLK_RST_NUM_CLKS; i++) monitor_clock(i);
      for (int i = 0; i < `CLK_RST_NUM_RSTS; i++) monitor_reset(i);
    join
  endtask
  virtual task monitor_clock(int idx);
    clk_rst_event evt;
    forever begin
      @(posedge vif.clk[idx]);
      m_clk_count[idx]++;
      if (m_last_posedge[idx] > 0)
        m_clk_period_measured[idx] = $realtime - m_last_posedge[idx];
      m_last_posedge[idx] = $realtime;
      evt = new();
      evt.ev_type = CLK_POSEDGE;
      evt.idx     = idx;
      evt.ev_time = $realtime;
      evt.period  = m_clk_period_measured[idx];
      event_port.write(evt);
    end
  endtask
  virtual task monitor_reset(int idx);
    clk_rst_event evt;
    forever begin
      @(negedge vif.rst_n[idx]);
      m_rst_count[idx]++;
      evt = new();
      evt.ev_type = RST_ASSERT;
      evt.idx     = idx;
      evt.ev_time = $realtime;
      event_port.write(evt);
      @(posedge vif.rst_n[idx]);
      evt = new();
      evt.ev_type = RST_DEASSERT;
      evt.ev_time = $realtime;
      event_port.write(evt);
    end
  endtask
  virtual function void report_phase(uvm_phase phase);
    `uvm_info("CLK_MON", "Clock Monitor Report:", UVM_NONE)
    for (int i = 0; i < `CLK_RST_NUM_CLKS; i++)
      `uvm_info("CLK_MON", $sformatf("  clk[%0d]: %0d edges, period=%.0fps",
                 i, m_clk_count[i], m_clk_period_measured[i]/1ps), UVM_NONE)
  endfunction
endclass : clk_rst_monitor

`endif // CLK_RST_MONITOR_SVH
