// Coverage Collector: UART_in_coverage_collector

class UART_in_coverage_collector extends uvm_subscriber #(UART_in_seq_item);
  `uvm_component_utils(UART_in_coverage_collector)

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void write(UART_in_seq_item t);
    `uvm_info("COV", $sformatf("Coverage sample: %s", t.convert2string()), UVM_HIGH)
  endfunction

endclass : UART_in_coverage_collector
