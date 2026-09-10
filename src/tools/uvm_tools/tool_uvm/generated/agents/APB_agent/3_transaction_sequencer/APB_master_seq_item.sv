// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_master_seq_item.sv
//   作者:     -
//   创建时间: 2026-09-09 17:58:44
//   修改时间: 2026-09-09 17:58:44
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════



// ============================================================
// Master Seq Item: APB_master_seq_item
// ============================================================

class APB_master_seq_item extends uvm_sequence_item;
  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack 自动化）──
  `uvm_object_utils_begin(APB_master_seq_item)
    `uvm_field_enum(xact_type_e, xact_type, UVM_DEFAULT)
    // master 字段
    `uvm_field_int(paddr, UVM_DEFAULT)
    `uvm_field_int(pwrite, UVM_DEFAULT)
    `uvm_field_int(pwdata, UVM_DEFAULT)
    // slave 响应字段
    `uvm_field_int(prdata, UVM_DEFAULT)
    `uvm_field_int(pslverr, UVM_DEFAULT)
  `uvm_object_utils_end

  typedef enum {READ, WRITE} xact_type_e;

  rand xact_type_e xact_type;

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

  function new(string name = "APB_master_seq_item");
    super.new(name);
  endfunction

  function string convert2string();
    return $sformatf("MST: type=%s", xact_type.name());
  endfunction
endclass : APB_master_seq_item
