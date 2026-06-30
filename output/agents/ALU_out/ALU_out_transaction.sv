// Sequence Item: ALU_out_seq_item

class ALU_out_seq_item extends uvm_sequence_item;
  rand bit [DATA_WIDTH-1:0] result; // is_compare=True, is_rand=False
  rand bit [FLAGS_WIDTH-1:0] flags; // is_compare=True, is_rand=False
  rand bit valid; // is_compare=False, is_rand=False

  // ─── 内建字段 ───
  int      req_id;
  int      tag;
  bit      error;
  realtime begin_time;

  // ─── Field Registration ───
  `uvm_object_utils_begin(ALU_out_seq_item)
    `uvm_field_int(result, UVM_ALL_ON)
    `uvm_field_int(flags, UVM_ALL_ON)
    `uvm_field_int(valid, UVM_ALL_ON)
    `uvm_field_int(req_id, UVM_ALL_ON)
    `uvm_field_int(tag, UVM_ALL_ON)
    `uvm_field_int(error, UVM_ALL_ON)
    `uvm_field_real(begin_time, UVM_ALL_ON)
  `uvm_object_utils_end
  constraint passive_c { }

  function new(string name = "ALU_out_seq_item");
    super.new(name);
  endfunction
endclass : ALU_out_seq_item