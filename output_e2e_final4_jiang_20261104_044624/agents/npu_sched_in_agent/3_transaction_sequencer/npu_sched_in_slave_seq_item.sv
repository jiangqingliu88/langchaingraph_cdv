// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_in_slave_seq_item.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════



// ============================================================
// Slave Seq Item: npu_sched_in_slave_seq_item
// ============================================================

// 继承 <name>_base_seq_item：xact_type 与 base_transaction_vars 由基类提供。
class npu_sched_in_slave_seq_item extends npu_sched_in_base_seq_item;
  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack 自动化）──

  // 请求字段（is_master=True：由 Monitor 回填，非随机）
  bit instr_valid; // 由 monitor 回填
  bit [7:0] instr_opcode; // 由 monitor 回填
  bit [2:0] instr_type; // 由 monitor 回填
  bit [2:0] instr_dtype; // 由 monitor 回填
  bit [7:0] instr_tile_id; // 由 monitor 回填
  bit [31:0] instr_src_addr; // 由 monitor 回填
  bit [31:0] instr_dst_addr; // 由 monitor 回填
  bit [1:0] barrier_type; // 由 monitor 回填
  bit [1:0] op_priority; // 由 monitor 回填

  // slave 响应字段（is_master=False：slave 生成）

  // 响应控制指令（由 Slave Sequence 填充）
  rand int       delay_cycles;
  rand bit [1:0] force_resp;
  rand bit       override_rdata;

  // pragma custom field_decl begin
  // pragma custom field_decl end
  constraint c_delay_range { delay_cycles inside {[0:50]}; }
  constraint c_resp_valid  { force_resp inside {2'b00, 2'b01, 2'b10, 2'b11}; }

  //   基类字段由基类的 utils 块注册，这里只注册新增字段
  `uvm_object_utils_begin(npu_sched_in_slave_seq_item)
    // 请求字段（由 monitor 回填）
    `uvm_field_int(instr_valid, UVM_DEFAULT)
    `uvm_field_int(instr_opcode, UVM_DEFAULT)
    `uvm_field_int(instr_type, UVM_DEFAULT)
    `uvm_field_int(instr_dtype, UVM_DEFAULT)
    `uvm_field_int(instr_tile_id, UVM_DEFAULT)
    `uvm_field_int(instr_src_addr, UVM_DEFAULT)
    `uvm_field_int(instr_dst_addr, UVM_DEFAULT)
    `uvm_field_int(barrier_type, UVM_DEFAULT)
    `uvm_field_int(op_priority, UVM_DEFAULT)
    // slave 响应字段
    // 响应控制指令
    `uvm_field_int(delay_cycles, UVM_DEFAULT)
    `uvm_field_int(force_resp, UVM_DEFAULT)
    `uvm_field_int(override_rdata, UVM_DEFAULT)
  `uvm_object_utils_end

  function new(string name = "npu_sched_in_slave_seq_item");
    super.new(name);
  endfunction

endclass : npu_sched_in_slave_seq_item
