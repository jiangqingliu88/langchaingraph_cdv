// ════════════════════════════════════════════════════════════════
// clk_rst_sequence.svh —— 时钟复位基类序列
// 职责: pre_body 从 sequencer 获取 cfg/vif（子类直接使用）
// 依赖: clk_rst_config.svh, clk_rst_if.svh
// ════════════════════════════════════════════════════════════════

`ifndef CLK_RST_SEQUENCE_SVH
`define CLK_RST_SEQUENCE_SVH

// ── 7. Sequence ──
class clk_rst_base_seq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(clk_rst_base_seq)
  clk_rst_config     cfg;
  virtual clk_rst_if vif;
  function new(string name = "clk_rst_base_seq");
    super.new(name);
  endfunction
  virtual task pre_body();
    if (!uvm_config_db #(clk_rst_config)::get(get_sequencer(), "", "cfg", cfg))
      `uvm_fatal("SEQ", "Config not set")
    if (!uvm_config_db #(virtual clk_rst_if)::get(get_sequencer(), "", "vif", vif))
      `uvm_fatal("SEQ", "Interface not set")
  endtask
endclass : clk_rst_base_seq

`endif // CLK_RST_SEQUENCE_SVH
