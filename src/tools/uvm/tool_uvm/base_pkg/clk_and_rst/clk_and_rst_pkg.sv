// ============================================================
// Clock & Reset VIP — 独立可复用
// ============================================================

`include "uvm_macros.svh"
import uvm_pkg::*;

`ifndef NUM_CLKS
  `define NUM_CLKS 1
`endif
`ifndef NUM_RSTS
  `define NUM_RSTS 1
`endif

// ── 1. Config ──
class clk_rst_config extends uvm_object;
  `uvm_object_utils(clk_rst_config)
  real    clk_period_ps    = 10000;
  real    clk_duty_cycle   = 50;
  bit     clk_start_value  = 0;
  real    clk_jitter_ps    = 0;
  int     clk_stop_after   = 0;
  bit     rst_active_low   = 1;
  int     rst_assert_cycles = 10;
  int     rst_recover_cycles = 5;
  bit     rst_start_value  = 0;
  bit     enable_clock_gating = 0;
  int     clock_gate_cycles   = 100;
  int     clock_ungate_cycles = 10;
  function new(string name = "clk_rst_config");
    super.new(name);
  endfunction
endclass : clk_rst_config

// ── 2. Interface ──
interface clk_rst_if #(
  parameter int NUM_CLKS = 1,
  parameter int NUM_RSTS = 1
)();
  logic [NUM_CLKS-1:0] clk;
  logic [NUM_RSTS-1:0] rst_n;
  logic [NUM_CLKS-1:0] clk_gate;
  logic [NUM_RSTS-1:0] rst_active;
  logic [NUM_CLKS-1:0] clk_running;
  clocking cb @(posedge clk[0]);
    input rst_n;
  endclocking
  modport mp (input clk, rst_n, output clk_gate);
endinterface : clk_rst_if

// ── 3. Event (Monitor 引用，放前面) ──
typedef enum { CLK_POSEDGE, CLK_NEGEDGE, RST_ASSERT, RST_DEASSERT } clk_rst_event_type;

class clk_rst_event extends uvm_sequence_item;
  `uvm_object_utils(clk_rst_event)
  clk_rst_event_type ev_type;
  int                idx;
  realtime           ev_time;
  realtime           period;
  function new(string name = "clk_rst_event");
    super.new(name);
  endfunction
endclass

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
      for (int i = 0; i < `NUM_CLKS; i++) drive_clock(i);
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

// ── 5. Reset Driver ──
class rst_driver extends uvm_driver #(uvm_sequence_item);
  `uvm_component_utils(rst_driver)
  virtual clk_rst_if vif;
  clk_rst_config     cfg;

  typedef struct { int assert_cycles; int recover_cycles; } rst_req_t;
  rst_req_t rst_req_queue[`NUM_RSTS][$];

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
      for (int i = 0; i < `NUM_RSTS; i++) drive_reset(i);
    join
  endtask
endclass : rst_driver

// ── 6. Monitor ──
class clk_rst_monitor extends uvm_monitor;
  `uvm_component_utils(clk_rst_monitor)
  virtual clk_rst_if vif;
  clk_rst_config     cfg;
  protected realtime m_clk_period_measured[`NUM_CLKS];
  protected int      m_clk_count[`NUM_CLKS];
  protected int      m_rst_count[`NUM_RSTS];
  protected realtime m_last_posedge[`NUM_CLKS];
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
      for (int i = 0; i < `NUM_CLKS; i++) monitor_clock(i);
      for (int i = 0; i < `NUM_RSTS; i++) monitor_reset(i);
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
    for (int i = 0; i < `NUM_CLKS; i++)
      `uvm_info("CLK_MON", $sformatf("  clk[%0d]: %0d edges, period=%.0fps",
                 i, m_clk_count[i], m_clk_period_measured[i]/1ps), UVM_NONE)
  endfunction
endclass : clk_rst_monitor

// ── 7. Sequence ──
class clk_rst_base_seq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(clk_rst_base_seq)
  clk_rst_config     cfg;
  virtual clk_rst_if vif;
  function new(string name = "clk_rst_base_seq");
    super.new(name);
  endfunction
  virtual task pre_body();
    if (!uvm_config_db #(clk_rst_config)::get(get_sequencer(), "", "cfg", cfg))
      `uvm_fatal("SEQ", "Config not set")
    if (!uvm_config_db #(virtual clk_rst_if)::get(get_sequencer(), "", "vif", vif))
      `uvm_fatal("SEQ", "Interface not set")
  endtask
endclass : clk_rst_base_seq

// ── 8. Agent ──
class clk_rst_agent extends uvm_agent;
  `uvm_component_utils(clk_rst_agent)
  clk_rst_config  cfg;
  clk_driver      drv;
  rst_driver      rst_drv;
  clk_rst_monitor mon;
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    cfg = clk_rst_config::type_id::create("cfg");
    uvm_config_db #(clk_rst_config)::set(this, "*", "cfg", cfg);
    drv    = clk_driver::type_id::create("drv", this);
    rst_drv = rst_driver::type_id::create("rst_drv", this);
    mon    = clk_rst_monitor::type_id::create("mon", this);
  endfunction
endclass : clk_rst_agent
