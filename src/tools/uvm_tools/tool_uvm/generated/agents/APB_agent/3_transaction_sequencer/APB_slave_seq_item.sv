// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_slave_seq_item.sv
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
// Slave Seq Item: APB_slave_seq_item
// ============================================================

class APB_slave_seq_item extends uvm_sequence_item;
  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack 自动化）──
  `uvm_object_utils_begin(APB_slave_seq_item)
    `uvm_field_enum(xact_type_e, xact_type, UVM_DEFAULT)
    // 请求字段（由 monitor 回填）
    `uvm_field_int(paddr, UVM_DEFAULT)
    `uvm_field_int(pwrite, UVM_DEFAULT)
    `uvm_field_int(pwdata, UVM_DEFAULT)
    // slave 响应字段
    `uvm_field_int(prdata, UVM_DEFAULT)
    `uvm_field_int(pslverr, UVM_DEFAULT)
    // 响应控制指令
    `uvm_field_int(delay_cycles, UVM_DEFAULT)
    `uvm_field_int(force_resp, UVM_DEFAULT)
    `uvm_field_int(override_rdata, UVM_DEFAULT)
  `uvm_object_utils_end

  typedef enum {READ, WRITE} xact_type_e;

  // 请求字段（is_master=True：由 Monitor 回填，非随机）
  xact_type_e xact_type;
  bit [ADDR_WIDTH-1:0] paddr; // 由 monitor 回填
  bit pwrite; // 由 monitor 回填
  bit [DATA_WIDTH-1:0] pwdata; // 由 monitor 回填

  // slave 响应字段（is_master=False：slave 生成）
  rand bit [DATA_WIDTH-1:0] prdata; // slave 响应
  rand bit pslverr; // slave 响应

  // 响应控制指令（由 Slave Sequence 填充）
  rand int       delay_cycles;
  rand bit [1:0] force_resp;
  rand bit       override_rdata;

  // pragma custom field_decl begin
  // pragma custom field_decl end
  constraint c_prdata_range { prdata inside {[0:32'hFFFF_FFFF]}; }
  constraint c_delay_range { delay_cycles inside {[0:50]}; }
  constraint c_resp_valid  { force_resp inside {2'b00, 2'b01, 2'b10, 2'b11}; }

  function new(string name = "APB_slave_seq_item");
    super.new(name);
  endfunction

  function string convert2string();
    return $sformatf("SLV: type=%s delay=%0d resp=%0b",
                     xact_type.name(), delay_cycles, force_resp);
  endfunction
endclass : APB_slave_seq_item
