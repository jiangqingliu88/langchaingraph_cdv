import uvm_pkg::*;
import apb_uart_in_pkg::*;
`include "uvm_macros.svh"

// Forward declaration: SCB 在 agent_loopback_scb.sv 中定义，此文件之后编译
typedef class apb_uart_in_loopback_scb;

// === Agent Loopback Env: apb_uart_in ===
// 单 Agent 自测环境 —— Driver → Monitor 闭环验证

class apb_uart_in_loopback_env extends uvm_env;
  `uvm_component_utils(apb_uart_in_loopback_env)

  apb_uart_in_agent        agent_h;
  apb_uart_in_loopback_scb scb_h;
  apb_uart_in_config       cfg;

  function new(string name = "apb_uart_in_loopback_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    cfg = apb_uart_in_config::type_id::create("cfg", this);
    cfg.is_active = UVM_ACTIVE;
    uvm_config_db #(apb_uart_in_config)::set(this, "*", "cfg", cfg);
    agent_h = apb_uart_in_agent::type_id::create("agent_h", this);
    scb_h   = apb_uart_in_loopback_scb::type_id::create("scb_h", this);
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    agent_h.drv.expected_port.connect(scb_h.expected_export);
    agent_h.mon.item_collected_port.connect(scb_h.actual_export);
  endfunction

endclass : apb_uart_in_loopback_env
