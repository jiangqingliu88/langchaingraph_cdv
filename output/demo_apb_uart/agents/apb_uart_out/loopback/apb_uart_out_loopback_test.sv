import uvm_pkg::*;
import apb_uart_out_pkg::*;
`include "uvm_macros.svh"

// === Agent Loopback Test: apb_uart_out ===
// Uses random_seq with actual body to send N transactions.
// Verifies Driver->Monitor closed-loop data consistency.

class apb_uart_out_loopback_test extends uvm_test;
  `uvm_component_utils(apb_uart_out_loopback_test)

  apb_uart_out_loopback_env env_h;
  int num_items = 20;

  function new(string name = "apb_uart_out_loopback_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    env_h = apb_uart_out_loopback_env::type_id::create("env_h", this);
  endfunction

  task run_phase(uvm_phase phase);
    apb_uart_out_random_seq seq;

    phase.raise_objection(this);

    `uvm_info("LB_TEST", "Starting apb_uart_out loopback test", UVM_NONE)

    // Wait for reset de-assertion (rst released at #100 in TB, first posedge at #105)
    #105ns;

    // Use random_seq (has actual body, unlike base_seq which is empty)
    seq = apb_uart_out_random_seq::type_id::create("seq");
    seq.num_transactions = num_items;
    seq.delay_min = 0;
    seq.delay_max = 0;
    seq.start(env_h.agent_h.sqr);

    // Brief wait for last item to propagate
    #30ns;

    `uvm_info("LB_TEST", $sformatf("Loopback test completed: %0d items sent", num_items), UVM_NONE)
    phase.drop_objection(this);
  endtask

endclass : apb_uart_out_loopback_test
