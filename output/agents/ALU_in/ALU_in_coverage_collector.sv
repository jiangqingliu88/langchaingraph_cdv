// Coverage Collector: ALU_in_coverage_collector

class ALU_in_coverage_collector extends uvm_subscriber #(ALU_in_seq_item);
  `uvm_component_utils(ALU_in_coverage_collector)

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void write(ALU_in_seq_item t);
    `uvm_info("COV", $sformatf("Coverage sample: %s", t.convert2string()), UVM_HIGH)
  endfunction

endclass : ALU_in_coverage_collector
