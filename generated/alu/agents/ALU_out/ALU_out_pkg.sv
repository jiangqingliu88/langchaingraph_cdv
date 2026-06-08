// Agent Package: ALU_out_pkg
package ALU_out_pkg;
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
  localparam int DATA_WIDTH = 32;
  localparam int FLAGS_WIDTH = 4;
  localparam int ALU_OP_WIDTH = 4;
  // HDL type definitions (mirror interface typedefs)
  typedef struct packed { logic N; logic Z; logic C; logic V; } alu_flags_t;
  // HVL type definitions
  typedef bit [DATA_WIDTH-1:0] alu_result_t;

  `include "ALU_out_interface_structure.sv"
  `include "ALU_out_transaction.sv"
  `include "ALU_out_config.sv"
  `include "ALU_out_driver.sv"
  `include "ALU_out_monitor.sv"
  `include "ALU_out_sequencer.sv"
  `include "ALU_out_base_seq.sv"
  `include "ALU_out_coverage_collector.sv"
  `include "ALU_out_agent.sv"
`ifdef ALU_out_loop_back_test
  `include "loopback/ALU_out_loopback_env.sv"
  `include "loopback/ALU_out_loopback_scb.sv"
  `include "loopback/ALU_out_loopback_test.sv"
`endif
endpackage : ALU_out_pkg