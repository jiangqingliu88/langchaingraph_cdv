// Agent Package: apb_uart_out_pkg
package apb_uart_out_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  // UVM callback macros — compatible with UVM 1.2 and 1800.2
  // In UVM 1.2, uvm_register_cb/uvm_do_callbacks are built-in via uvm_macros.svh.
  // In 1800.2, callbacks use uvm_callback pool; stubs are no-ops.
  `ifndef uvm_register_cb
  `define uvm_register_cb(T, CB)  /* callback disabled (UVM 1800.2 compat mode) */
  `endif
  `ifndef uvm_do_callbacks
  `define uvm_do_callbacks(T, CB, METHOD)  /* callback disabled (UVM 1800.2 compat mode) */
  `endif
  localparam int DATA_WIDTH = 32;

  `include "apb_uart_out_interface_structure.sv"
  `include "apb_uart_out_transaction.sv"
  `include "apb_uart_out_config.sv"
  `include "apb_uart_out_driver.sv"
  `include "apb_uart_out_monitor.sv"
  `include "apb_uart_out_sequencer.sv"
  `include "apb_uart_out_base_seq.sv"
  `include "apb_uart_out_coverage_collector.sv"
  `include "apb_uart_out_agent.sv"
`ifdef apb_uart_out_loop_back_test
  `include "loopback/apb_uart_out_loopback_env.sv"
  `include "loopback/apb_uart_out_loopback_scb.sv"
  `include "loopback/apb_uart_out_loopback_test.sv"
`endif
endpackage : apb_uart_out_pkg