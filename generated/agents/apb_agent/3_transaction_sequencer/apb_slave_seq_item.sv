// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_slave_seq_item.sv
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
// Slave Seq Item: apb_slave_seq_item
// ============================================================

// 继承 <name>_base_seq_item：xact_type 与 base_transaction_vars 由基类提供。
class apb_slave_seq_item extends apb_base_seq_item;
  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack 自动化）──
  //   基类字段由基类的 utils 块注册，这里只注册新增字段
  `uvm_object_utils_begin(apb_slave_seq_item)
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

  // 请求字段（is_master=True：由 Monitor 回填，非随机）
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

  function new(string name = "apb_slave_seq_item");
    super.new(name);
  endfunction

endclass : apb_slave_seq_item
