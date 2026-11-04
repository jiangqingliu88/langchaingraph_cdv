// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_slave_agent.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Slave Agent: npu_sched_out_slave_agent
// ============================================================

class npu_sched_out_slave_agent extends uvm_agent;
  `uvm_component_utils(npu_sched_out_slave_agent)

  npu_sched_out_slave_sequencer sequencer;
  npu_sched_out_slave_driver    driver;
  npu_sched_out_port_monitor   monitor;
  npu_sched_out_port_config    cfg;
  uvm_analysis_port #(npu_sched_out_slave_seq_item) npu_sched_out_slave_agent_ap;  // slave 侧抓包
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    void'(uvm_config_db#(npu_sched_out_port_config)::get(this, "", "cfg", cfg));
    if (cfg == null)
      cfg = npu_sched_out_port_config::type_id::create("cfg", this);

    // 虚拟接口：tb_top 用 `*.<agent 实例路径>*` 塞进 config_db，这里取出存 cfg.vif
    if (cfg.vif == null)
      void'(uvm_config_db#(virtual npu_sched_out_if)::get(this, "", "vif", cfg.vif));

    // ⚠️ 子组件的 cfg / vif 必须在 **create 之前** set（UVM 的 build 自上而下，
    // 子组件 build_phase 紧接父组件之后执行；放 connect_phase 就太晚了，
    // driver 会 `uvm_fatal("[CFG] Config not set")`）。
    uvm_config_db#(npu_sched_out_port_config)::set(this, "monitor", "cfg", cfg);
    uvm_config_db#(virtual npu_sched_out_if)::set(this, "monitor", "vif", cfg.vif);

    monitor = npu_sched_out_port_monitor::type_id::create("monitor", this);
    npu_sched_out_slave_agent_ap= monitor.slave_mon_ap;
    if (cfg.is_active == UVM_ACTIVE) begin
      uvm_config_db#(npu_sched_out_port_config)::set(this, "sequencer", "cfg", cfg);
      sequencer = npu_sched_out_slave_sequencer::type_id::create("sequencer", this);
      uvm_config_db#(npu_sched_out_port_config)::set(this, "driver", "cfg", cfg);
      uvm_config_db#(virtual npu_sched_out_if)::set(this, "driver", "vif", cfg.vif);
      driver    = npu_sched_out_slave_driver::type_id::create("driver", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (cfg.is_active == UVM_ACTIVE) begin
      driver.seq_item_port.connect(sequencer.seq_item_export);
      // ★ 将 Sequencer 句柄传给 Monitor（事件驱动）
      uvm_config_db#(npu_sched_out_slave_sequencer)::set(this, "monitor", "sqr", sequencer);
    end
  endfunction
endclass : npu_sched_out_slave_agent
