// Coverage Collector: apb_uart_in_coverage_collector

class apb_uart_in_coverage_collector extends uvm_subscriber #(apb_uart_in_seq_item);
  `uvm_component_utils(apb_uart_in_coverage_collector)

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void write(apb_uart_in_seq_item t);
    `uvm_info("COV", $sformatf("Coverage sample: %s", t.convert2string()), UVM_HIGH)
  endfunction

endclass : apb_uart_in_coverage_collector
