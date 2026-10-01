// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_slave_agent.sv
//   作者:     JQLIU
//   创建时间: 2026-09-12
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: jqliu@nanocorechip.com
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Slave Agent: apb_slave_agent
// ============================================================

class apb_slave_agent extends uvm_agent;
  `uvm_component_utils(apb_slave_agent)

  apb_slave_sequencer sequencer;
  apb_slave_driver    driver;
  apb_port_monitor   monitor;
  apb_port_config    cfg;
  uvm_analysis_port #(apb_slave_seq_item) apb_slave_agent_ap;  // slave 侧抓包
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    apb_slave_agent_ap= monitor.slave_mon_ap;
    uvm_config_db#(apb_port_config)::get(this, "", "cfg", cfg);
    if (cfg == null)
      cfg = apb_port_config::type_id::create("cfg", this);

    monitor = apb_port_monitor::type_id::create("monitor", this);
    if (cfg.is_active == UVM_ACTIVE) begin
      uvm_config_db#(apb_port_config)::set(this, "sequencer", "cfg", cfg);
      sequencer = apb_slave_sequencer::type_id::create("sequencer", this);
      driver    = apb_slave_driver::type_id::create("driver", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (cfg.is_active == UVM_ACTIVE) begin
      driver.seq_item_port.connect(sequencer.seq_item_export);
      // ★ 将 Sequencer 句柄传给 Monitor（事件驱动）
      uvm_config_db#(apb_slave_sequencer)::set(this, "monitor", "sqr", sequencer);
    end
    uvm_config_db#(virtual apb_if)::set(this, "monitor", "vif", cfg.vif);
    uvm_config_db#(apb_port_config)::set(this, "monitor", "cfg", cfg);
    if (driver != null) begin
      uvm_config_db#(virtual apb_if)::set(this, "driver", "vif", cfg.vif);
      uvm_config_db#(apb_port_config)::set(this, "driver", "cfg", cfg);
    end
  endfunction
endclass : apb_slave_agent
