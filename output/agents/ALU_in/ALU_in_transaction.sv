// Sequence Item: ALU_in_seq_item

class ALU_in_seq_item extends uvm_sequence_item;
  `uvm_object_utils(ALU_in_seq_item)
  rand bit [ALU_WIDTH-1:0] a; // is_compare=True, is_rand=True
  rand bit [ALU_WIDTH-1:0] b; // is_compare=True, is_rand=True
  rand alu_op_t op; // is_compare=True, is_rand=True
  rand alu_result_t result; // is_compare=True, is_rand=False

  // ── 物理端口字段（Driver 驱动 / Monitor 采样）──
  rand logic valid;  // output
  rand logic ready;  // input

  // ─── 内建字段 ───
  int      req_id;
  int      tag;
  bit      error;
  realtime begin_time;
  constraint valid_op_c { op inside {ADD, SUB, MUL}; }
  constraint data_range_c { a < 128; b < 128; }

  function new(string name = "ALU_in_seq_item");
    super.new(name);
  endfunction
endclass : ALU_in_seq_item