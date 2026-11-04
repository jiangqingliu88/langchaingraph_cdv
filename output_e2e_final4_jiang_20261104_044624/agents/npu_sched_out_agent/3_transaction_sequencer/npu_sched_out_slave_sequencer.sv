// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_slave_sequencer.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Slave Sequencer: npu_sched_out_slave_sequencer
// ============================================================

class npu_sched_out_slave_sequencer extends uvm_sequencer #(npu_sched_out_slave_seq_item);
  `uvm_component_utils(npu_sched_out_slave_sequencer)

  // ★ 核心：接收 Monitor 抓包的事件 FIFO（事件驱动）
  uvm_tlm_analysis_fifo #(npu_sched_out_slave_seq_item) req_fifo;

  // ★ 配置句柄（agent build_phase 经 config_db 传入；
  //   sequence body 内通过 p_sequencer.get_cfg(...) 获取）
  npu_sched_out_port_config cfg;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    req_fifo = new("req_fifo", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    void'(uvm_config_db#(npu_sched_out_port_config)::get(this, "", "cfg", cfg));
  endfunction

  // ★ 向序列提供配置（sequence 侧: p_sequencer.get_cfg(cfg)）
  function void get_cfg(ref npu_sched_out_port_config _cfg);
    _cfg = cfg;
  endfunction
endclass : npu_sched_out_slave_sequencer
