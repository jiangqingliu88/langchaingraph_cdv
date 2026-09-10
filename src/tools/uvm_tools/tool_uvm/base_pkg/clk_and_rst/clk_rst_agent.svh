// ════════════════════════════════════════════════════════════════
// clk_rst_agent.svh —— 时钟复位 Agent（clk_driver + rst_driver + monitor）
// 职责: 创建 cfg 并经 config_db 广播（"*"），例化三个子组件
// 依赖: clk_driver.svh, rst_driver.svh, clk_rst_monitor.svh
// ════════════════════════════════════════════════════════════════

`ifndef CLK_RST_AGENT_SVH
`define CLK_RST_AGENT_SVH

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

`endif // CLK_RST_AGENT_SVH
