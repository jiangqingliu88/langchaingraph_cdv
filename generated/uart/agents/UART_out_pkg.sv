// Agent Package: UART_out_pkg
package UART_out_pkg;
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

  `include "UART_out_interface_structure.sv"
  `include "UART_out_transaction.sv"
  `include "UART_out_config.sv"
  `include "UART_out_driver.sv"
  `include "UART_out_monitor.sv"
  `include "UART_out_sequencer.sv"
  `include "UART_out_base_seq.sv"
  `include "UART_out_coverage_collector.sv"
  `include "UART_out_agent.sv"

endpackage : UART_out_pkg