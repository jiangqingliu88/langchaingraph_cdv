// Sequence Item: ALU_in_seq_item

class ALU_in_seq_item extends uvm_sequence_item;
  rand bit [ALU_WIDTH-1:0] a; // is_compare=True, is_rand=True
  rand bit [ALU_WIDTH-1:0] b; // is_compare=True, is_rand=True
  rand alu_op_t op; // is_compare=True, is_rand=True
  rand alu_result_t result; // is_compare=True, is_rand=False

  // ─── 内建字段 ───
  int      req_id;
  int      tag;
  bit      error;
  realtime begin_time;

  // ─── Field Registration ───
  `uvm_object_utils_begin(ALU_in_seq_item)
    `uvm_field_int(a, UVM_ALL_ON)
    `uvm_field_int(b, UVM_ALL_ON)
    `uvm_field_int(op, UVM_ALL_ON)
    `uvm_field_int(result, UVM_ALL_ON)
    `uvm_field_int(req_id, UVM_ALL_ON)
    `uvm_field_int(tag, UVM_ALL_ON)
    `uvm_field_int(error, UVM_ALL_ON)
    `uvm_field_real(begin_time, UVM_ALL_ON)
  `uvm_object_utils_end
  constraint valid_op_c { op inside {ADD, SUB, MUL}; }
  constraint data_range_c { a < 128; b < 128; }

  function new(string name = "ALU_in_seq_item");
    super.new(name);
  endfunction
endclass : ALU_in_seq_item