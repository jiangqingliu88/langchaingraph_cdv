// Agent Package: UART_in_pkg
package UART_in_pkg;
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

  `include "UART_in_interface_structure.sv"
  `include "UART_in_transaction.sv"
  `include "UART_in_config.sv"
  `include "UART_in_driver.sv"
  `include "UART_in_monitor.sv"
  `include "UART_in_sequencer.sv"
  `include "UART_in_base_seq.sv"
  `include "UART_in_coverage_collector.sv"
  `include "UART_in_agent.sv"

endpackage : UART_in_pkg