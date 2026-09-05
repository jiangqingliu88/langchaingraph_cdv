// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_reg_adapter.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Reg Adapter: APB_reg_adapter
// ============================================================
// RAL 集成：uvm_reg → APB_master_seq_item 双向转换

class APB_reg_adapter extends uvm_reg_adapter;
  `uvm_object_utils(APB_reg_adapter)

  int m_bytes_per_word = 4;

  function new(string name = "APB_reg_adapter");
    super.new(name);
    provides_responses = 1;
  endfunction

  function uvm_sequence_item reg2bus(const ref uvm_reg_bus_op rw);
    APB_master_seq_item req = APB_master_seq_item::type_id::create("reg_req");
    req.xact_type = (rw.kind == UVM_READ) ? APB_master_seq_item::READ
                                          : APB_master_seq_item::WRITE;
    return req;
  endfunction

  function void bus2reg(uvm_sequence_item bus_item, ref uvm_reg_bus_op rw);
    APB_master_seq_item rsp;
    if (!$cast(rsp, bus_item)) return;
    rw.kind = (rsp.xact_type == APB_master_seq_item::READ) ? UVM_READ : UVM_WRITE;
    rw.status = UVM_IS_OK;  // 协议错误映射在此扩展
  endfunction
endclass : APB_reg_adapter
