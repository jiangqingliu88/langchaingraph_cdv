// UVM C-Model Predictor: alu
// Generic: signal list from context, auto-generated
`ifndef ALU_CMODEL_PREDICTOR_SV
`define ALU_CMODEL_PREDICTOR_SV

import uvm_pkg::*;
`include "uvm_macros.svh"

import "DPI-C" function void alu_dpi_init();
import "DPI-C" function void alu_dpi_predict(
    input int unsigned a,
    input int unsigned b,
    input int unsigned op,
    output int unsigned result,
    output int unsigned flags,
    output int unsigned valid
);
import "DPI-C" function void alu_dpi_shutdown();

class alu_cmodel_predictor extends uvm_component;
  `uvm_component_utils(alu_cmodel_predictor)

  uvm_analysis_imp #(ALU_in_seq_item, alu_cmodel_predictor) analysis_export;
  uvm_analysis_port #(ALU_out_seq_item) predicted_port;

  protected int m_predictions = 0;
  protected bit m_initialized = 0;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    analysis_export = new("analysis_export", this);
    predicted_port  = new("predicted_port", this);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!m_initialized) begin
      alu_dpi_init();
      m_initialized = 1;
    end
  endfunction

  virtual function void write(ALU_in_seq_item t);
    ALU_out_seq_item pred;
    int unsigned dpi_result;
    int unsigned dpi_flags;
    int unsigned dpi_valid;
    if (!m_initialized) begin
      alu_dpi_init(); m_initialized = 1;
    end
    alu_dpi_predict(
      .a(t.a),
      .b(t.b),
      .op(t.op),
      .result(dpi_result),
      .flags(dpi_flags),
      .valid(dpi_valid)
    );
    pred = ALU_out_seq_item::type_id::create("pred");
    pred.result = dpi_result;
    pred.flags = dpi_flags;
    pred.valid = dpi_valid;
    predicted_port.write(pred);
    m_predictions++;
  endfunction

  virtual function void report_phase(uvm_phase phase);
    `uvm_info("CMODEL", $sformatf("C-Model: %0d predictions", m_predictions), UVM_NONE)
  endfunction

endclass : alu_cmodel_predictor

`endif
