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
    // 优先用环境传进来的配置（env 按 YAML 的 period / duty / 复位拍数建好后，
    // set 在本 agent 的精确路径上）。拿不到才自建一份默认值 ——
    // 原实现无条件 `create`，会把 env 配的时钟周期**悄悄丢掉**（不报错，
    // 只是跑在默认 10ns 上）。
    if (!uvm_config_db #(clk_rst_config)::get(this, "", "cfg", cfg))
      cfg = clk_rst_config::type_id::create("cfg");
    uvm_config_db #(clk_rst_config)::set(this, "*", "cfg", cfg);
    drv    = clk_driver::type_id::create("drv", this);
    rst_drv = rst_driver::type_id::create("rst_drv", this);
    mon    = clk_rst_monitor::type_id::create("mon", this);
  endfunction
endclass : clk_rst_agent

`endif // CLK_RST_AGENT_SVH
