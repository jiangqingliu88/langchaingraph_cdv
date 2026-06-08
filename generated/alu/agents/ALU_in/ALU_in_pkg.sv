// Agent Package: ALU_in_pkg
package ALU_in_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  // UVM-1.2 callback macros (use built-in if available, otherwise stub)
  `ifndef uvm_register_cb
  `define uvm_register_cb(T, CB) \
     static local bit m_register_cb_``CB = uvm_callbacks #(T,CB)::m_register_pair(`"T`",`"CB`");
  `endif
  `ifndef uvm_do_callbacks
  `define uvm_do_callbacks(T, CB, METHOD) \
     uvm_callbacks #(T,CB)::m_do_callbacks(this, METHOD)
  `endif
  localparam int ALU_WIDTH = 32;
  localparam int ALU_OP_WIDTH = 4;
  // HDL type definitions (mirror interface typedefs)
  typedef enum logic [2:0] {ADD=3'b000, SUB=3'b001, MUL=3'b010} alu_op_t;
  typedef logic [ALU_WIDTH-1:0] alu_data_t;
  // HVL type definitions
  typedef bit [2*ALU_WIDTH-1:0] alu_result_t;

  `include "ALU_in_interface_structure.sv"
  `include "ALU_in_transaction.sv"
  `include "ALU_in_config.sv"
  `include "ALU_in_driver.sv"
  `include "ALU_in_monitor.sv"
  `include "ALU_in_sequencer.sv"
  `include "ALU_in_base_seq.sv"
  `include "ALU_in_coverage_collector.sv"
  `include "ALU_in_agent.sv"
`ifdef ALU_in_loop_back_test
  `include "loopback/ALU_in_loopback_env.sv"
  `include "loopback/ALU_in_loopback_scb.sv"
  `include "loopback/ALU_in_loopback_test.sv"
`endif
endpackage : ALU_in_pkg