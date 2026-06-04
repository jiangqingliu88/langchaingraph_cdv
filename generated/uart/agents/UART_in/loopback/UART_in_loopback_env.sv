import uvm_pkg::*;
typedef class UART_in_loopback_scb;
import UART_in_pkg::*;
`include "uvm_macros.svh"

// === Agent Loopback Env: UART_in ===
// 单 Agent 自测环境 —— Driver → Monitor 闭环验证

class UART_in_loopback_env extends uvm_env;
  `uvm_component_utils(UART_in_loopback_env)

  UART_in_agent        agent_h;
  UART_in_loopback_scb scb_h;
  UART_in_config       cfg;

  function new(string name = "UART_in_loopback_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    cfg = UART_in_config::type_id::create("cfg");
    cfg.is_active = UVM_ACTIVE;
    uvm_config_db #(UART_in_config)::set(this, "*", "cfg", cfg);
    agent_h = UART_in_agent::type_id::create("agent_h", this);
    scb_h  = UART_in_loopback_scb::type_id::create("scb_h", this);
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    // Driver.expected_port → Scoreboard.expected_export (期望值)
    agent_h.drv.expected_port.connect(scb_h.expected_export);
    // Monitor.item_collected_port → Scoreboard.actual_export (实际值)
    agent_h.mon.item_collected_port.connect(scb_h.actual_export);
  endfunction

endclass : UART_in_loopback_env
