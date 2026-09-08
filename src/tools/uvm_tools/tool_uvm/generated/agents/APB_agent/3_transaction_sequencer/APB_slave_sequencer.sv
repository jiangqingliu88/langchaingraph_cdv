// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_slave_sequencer.sv
//   作者:     -
//   创建时间: 2026-09-07 23:32:17
//   修改时间: 2026-09-07 23:32:17
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Slave Sequencer: APB_slave_sequencer
// ============================================================

class APB_slave_sequencer extends uvm_sequencer #(APB_slave_seq_item);
  `uvm_component_utils(APB_slave_sequencer)

  // ★ 核心：接收 Monitor 抓包的事件 FIFO（事件驱动）
  uvm_tlm_analysis_fifo #(APB_slave_seq_item) req_fifo;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    req_fifo = new("req_fifo", this);
  endfunction
endclass : APB_slave_sequencer
