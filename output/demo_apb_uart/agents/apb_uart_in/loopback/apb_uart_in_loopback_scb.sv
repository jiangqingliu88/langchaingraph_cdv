import uvm_pkg::*;
import apb_uart_in_pkg::*;
`include "uvm_macros.svh"

// === Agent Loopback Scoreboard: apb_uart_in ===
// expected_export ← Driver.expected_port (期望值)
// actual_export   ← Monitor.item_collected_port (实际值)
// 逐项比对，验证 Agent Driver→DUT→Monitor 数据闭环

`uvm_analysis_imp_decl(_expected)
`uvm_analysis_imp_decl(_actual)

class apb_uart_in_loopback_scb extends uvm_scoreboard;
  `uvm_component_utils(apb_uart_in_loopback_scb)

  // 双端口：expected 来自 Driver，actual 来自 Monitor
  uvm_analysis_imp_expected #(apb_uart_in_seq_item, apb_uart_in_loopback_scb) expected_export;
  uvm_analysis_imp_actual   #(apb_uart_in_seq_item, apb_uart_in_loopback_scb) actual_export;

  protected apb_uart_in_seq_item  expected_q[$];
  protected int m_matched    = 0;
  protected int m_mismatched = 0;
  protected int m_total      = 0;

  function new(string name = "apb_uart_in_loopback_scb", uvm_component parent = null);
    super.new(name, parent);
    expected_export = new("expected_export", this);
    actual_export   = new("actual_export",   this);
  endfunction

  // ── Driver 发来期望值 ──
  virtual function void write_expected(apb_uart_in_seq_item exp);
    expected_q.push_back(exp);
  endfunction

  // ── Monitor 发来实际值 ──
  virtual function void write_actual(apb_uart_in_seq_item act);
    m_total++;
    if (expected_q.size() > 0) begin
      apb_uart_in_seq_item exp = expected_q.pop_front();
      if (exp.compare(act)) begin
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

  virtual function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    `uvm_info("SCB_LOOP", $sformatf(
      "Scoreboard: total=%0d matched=%0d mismatched=%0d pending=%0d",
      m_total, m_matched, m_mismatched, expected_q.size()), UVM_NONE)
  endfunction

endclass : apb_uart_in_loopback_scb
