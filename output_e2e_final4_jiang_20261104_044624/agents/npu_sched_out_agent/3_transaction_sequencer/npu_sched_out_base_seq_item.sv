// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_base_seq_item.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════



// ============================================================
// Base Seq Item: npu_sched_out_base_seq_item
// ============================================================
// master / slave seq_item 的共同基类，承载「两侧都有」的东西：
//   - xact_type（READ/WRITE）—— 两侧都要判方向
//   - base_transaction_vars     —— 两侧共用的字段（如 addr / data）
//   - base_transaction_constraints —— 两侧都成立的约束
// 各侧专有的字段与约束留在 <name>_{master,slave}_seq_item 里
// （按 transaction_vars 的 is_master 划分）。
//
// 依赖顺序：本文件必须在 <name>_master_seq_item.sv / _slave_seq_item.sv
// **之前** include（见 agent_pkg.sv.j2）——派生类要引用 xact_type_e，
// SystemVerilog 要求先声明后使用。
//
// 字段注册：本类的字段由这里的 uvm_object_utils_begin/end 注册；派生类各自
// 注册自己的字段。UVM 的 do_copy/do_compare/do_print 会沿继承链调 super，
// 故基类字段不会漏。

class npu_sched_out_base_seq_item extends uvm_sequence_item;

  // ── 事务方向（两侧共用）──
  //typedef enum {READ, WRITE} xact_type_e;
  // 注：声明为 rand。master 侧需要随机化它；slave 侧由 monitor 显式赋值，
  //     rand 不阻碍显式赋值，故两侧共用一个声明是安全的。
  rand xact_type_e xact_type;

  // pragma custom field_decl begin
  // pragma custom field_decl end

  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack 自动化）──
  `uvm_object_utils_begin(npu_sched_out_base_seq_item)
    `uvm_field_enum(xact_type_e, xact_type, UVM_DEFAULT)
  `uvm_object_utils_end

  function new(string name = "npu_sched_out_base_seq_item");
    super.new(name);
  endfunction

endclass : npu_sched_out_base_seq_item
