// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_slave_sequencer.sv
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
// Slave Sequencer: apb_slave_sequencer
// ============================================================

class apb_slave_sequencer extends uvm_sequencer #(apb_slave_seq_item);
  `uvm_component_utils(apb_slave_sequencer)

  // ★ 核心：接收 Monitor 抓包的事件 FIFO（事件驱动）
  uvm_tlm_analysis_fifo #(apb_slave_seq_item) req_fifo;

  // ★ 配置句柄（agent build_phase 经 config_db 传入；
  //   sequence body 内通过 p_sequencer.get_cfg(...) 获取）
  apb_port_config cfg;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    req_fifo = new("req_fifo", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(apb_port_config)::get(this, "", "cfg", cfg);
  endfunction

  // ★ 向序列提供配置（sequence 侧: p_sequencer.get_cfg(cfg)）
  function void get_cfg(ref apb_port_config _cfg);
    _cfg = cfg;
  endfunction
endclass : apb_slave_sequencer
