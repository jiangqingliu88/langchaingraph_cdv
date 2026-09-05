// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_slave_agent.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Slave Agent: APB_slave_agent
// ============================================================

class APB_slave_agent extends uvm_agent;
  `uvm_component_utils(APB_slave_agent)

  APB_slave_sequencer sequencer;
  APB_slave_driver    driver;
  APB_slave_monitor   monitor;
  APB_slave_config    cfg;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(APB_slave_config)::get(this, "", "cfg", cfg);
    if (cfg == null)
      cfg = APB_slave_config::type_id::create("cfg", this);

    monitor = APB_slave_monitor::type_id::create("monitor", this);
    if (cfg.is_active == UVM_ACTIVE) begin
      sequencer = APB_slave_sequencer::type_id::create("sequencer", this);
      driver    = APB_slave_driver::type_id::create("driver", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (cfg.is_active == UVM_ACTIVE) begin
      driver.seq_item_port.connect(sequencer.seq_item_export);
      // ★ 将 Sequencer 句柄传给 Monitor（事件驱动）
      uvm_config_db#(APB_slave_sequencer)::set(this, "monitor", "sqr", sequencer);
    end
    uvm_config_db#(virtual APB_if)::set(this, "monitor", "vif", cfg.vif);
    uvm_config_db#(APB_slave_config)::set(this, "monitor", "cfg", cfg);
    if (driver != null) begin
      uvm_config_db#(virtual APB_if)::set(this, "driver", "vif", cfg.vif);
      uvm_config_db#(APB_slave_config)::set(this, "driver", "cfg", cfg);
    end
  endfunction
endclass : APB_slave_agent
