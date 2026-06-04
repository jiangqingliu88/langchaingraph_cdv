// Coverage Collector: AXI_in_coverage_collector

class AXI_in_coverage_collector extends uvm_subscriber #(AXI_in_seq_item);
  `uvm_component_utils(AXI_in_coverage_collector)

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void write(AXI_in_seq_item t);
    `uvm_info("COV", $sformatf("Coverage sample: %s", t.convert2string()), UVM_HIGH)
  endfunction

endclass : AXI_in_coverage_collector
