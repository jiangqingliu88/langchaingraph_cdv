// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_master_agent.sv
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
// Master Agent: apb_master_agent
// ============================================================

class apb_master_agent extends uvm_agent;
  `uvm_component_utils(apb_master_agent)

  apb_master_sequencer sequencer;
  apb_master_driver    driver;
  apb_port_monitor   monitor;
  apb_port_config    cfg;
  uvm_analysis_port #(apb_master_seq_item) apb_master_agent_ap;         // master 侧抓包
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(apb_port_config)::get(this, "", "cfg", cfg);
    if (cfg == null)
      cfg = apb_port_config::type_id::create("cfg", this);

    monitor = apb_port_monitor::type_id::create("monitor", this);
    if (cfg.is_active == UVM_ACTIVE) begin
      uvm_config_db#(apb_port_config)::set(this, "sequencer", "cfg", cfg);
      sequencer = apb_master_sequencer::type_id::create("sequencer", this);
      driver    = apb_master_driver::type_id::create("driver", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
     apb_maser_agent_ap= monitor.master_mon_ap;
    if (cfg.is_active == UVM_ACTIVE)
      driver.seq_item_port.connect(sequencer.seq_item_export);
    uvm_config_db#(virtual apb_if)::set(this, "monitor", "vif", cfg.vif);
    uvm_config_db#(apb_port_config)::set(this, "monitor", "cfg", cfg);
    if (driver != null) begin
      uvm_config_db#(virtual apb_if)::set(this, "driver", "vif", cfg.vif);
      uvm_config_db#(apb_port_config)::set(this, "driver", "cfg", cfg);
    end
  endfunction
endclass : apb_master_agent
