// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_master_seq_item.sv
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
// Master Seq Item: apb_master_seq_item
// ============================================================

// 继承 <name>_base_seq_item：xact_type 与 base_transaction_vars 由基类提供，
// 本类只声明按 is_master 划分给 master/slave 的专有字段。
class apb_master_seq_item extends apb_base_seq_item;
  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack 自动化）──
  //   基类字段由基类的 utils 块注册（do_* 会沿继承链调 super），这里只注册新增字段
  `uvm_object_utils_begin(apb_master_seq_item)
    // master 字段
    `uvm_field_int(paddr, UVM_DEFAULT)
    `uvm_field_int(pwrite, UVM_DEFAULT)
    `uvm_field_int(pwdata, UVM_DEFAULT)
    // slave 响应字段
    `uvm_field_int(prdata, UVM_DEFAULT)
    `uvm_field_int(pslverr, UVM_DEFAULT)
  `uvm_object_utils_end

  // ── master 字段（is_master=True：master 驱动/生成）──
  rand bit [ADDR_WIDTH-1:0] paddr; // is_compare=True, is_rand=True
  rand bit pwrite; // is_compare=True, is_rand=True
  rand bit [DATA_WIDTH-1:0] pwdata; // is_compare=True, is_rand=True

  // ── slave 响应字段（is_master=False：master 采样）──
  bit [DATA_WIDTH-1:0] prdata; // slave 响应，master 采样
  bit pslverr; // slave 响应，master 采样

  // pragma custom field_decl begin
  // pragma custom field_decl end
  constraint c_paddr_align { paddr[1:0] == 2'b00; }

  function new(string name = "apb_master_seq_item");
    super.new(name);
  endfunction

endclass : apb_master_seq_item
