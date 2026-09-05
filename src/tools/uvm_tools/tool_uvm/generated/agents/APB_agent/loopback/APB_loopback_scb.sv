// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_loopback_scb.sv
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
// Loopback Scoreboard: APB_loopback_scb
// ============================================================
// expected_export ← master monitor (master 实际驱动的字段)
// actual_export   ← slave monitor  (slave 观察到的字段)
// 比较 master_seq_item 与 slave_seq_item 的 is_compare 公共字段
import uvm_pkg::*;
import APB_pkg::*;
`include "uvm_macros.svh"

`uvm_analysis_imp_decl(_expected)
`uvm_analysis_imp_decl(_actual)

class APB_loopback_scb extends uvm_scoreboard;
  `uvm_component_utils(APB_loopback_scb)

  uvm_analysis_imp_expected #(APB_master_seq_item, APB_loopback_scb) expected_export;
  uvm_analysis_imp_actual   #(APB_slave_seq_item,  APB_loopback_scb) actual_export;

  protected APB_master_seq_item expected_q[$];
  protected int m_matched    = 0;
  protected int m_mismatched = 0;
  protected int m_total      = 0;

  function new(string name = "APB_loopback_scb", uvm_component parent = null);
    super.new(name, parent);
    expected_export = new("expected_export", this);
    actual_export   = new("actual_export",   this);
  endfunction

  virtual function void write_expected(APB_master_seq_item exp);
    expected_q.push_back(exp);
  endfunction

  virtual function void write_actual(APB_slave_seq_item act);
    m_total++;
    if (expected_q.size() > 0) begin
      APB_master_seq_item exp = expected_q.pop_front();
      if (compare_fields(exp, act)) begin
        m_matched++;
        `uvm_info("SCB_LOOP_PASS", $sformatf("[PASS] #%0d matched", m_total), UVM_MEDIUM)
      end else begin
        m_mismatched++;
        `uvm_error("SCB_LOOP", $sformatf("[FAIL] #%0d mismatched\n  exp=%s\n  act=%s",
          m_total, exp.convert2string(), act.convert2string()))
      end
    end else begin
      m_mismatched++;
      `uvm_warning("SCB_LOOP", "Received actual without expected")
    end
  endfunction

  // 比较 master_seq_item 与 slave_seq_item 的 is_compare 公共字段
  virtual function bit compare_fields(APB_master_seq_item exp,
                                      APB_slave_seq_item act);
    bit ok = 1;
    ok &= (exp.paddr == act.paddr);
    ok &= (exp.pwrite == act.pwrite);
    ok &= (exp.pwdata == act.pwdata);
    return ok;
  endfunction

  virtual function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    `uvm_info("SCB_LOOP", $sformatf(
      "Scoreboard: total=%0d matched=%0d mismatched=%0d pending=%0d",
      m_total, m_matched, m_mismatched, expected_q.size()), UVM_NONE)
  endfunction

endclass : APB_loopback_scb
