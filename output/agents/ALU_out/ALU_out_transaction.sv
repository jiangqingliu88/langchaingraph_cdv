// Sequence Item: ALU_out_seq_item

class ALU_out_seq_item extends uvm_sequence_item;
  `uvm_object_utils(ALU_out_seq_item)
  rand bit [DATA_WIDTH-1:0] result; // is_compare=True, is_rand=False
  rand bit [FLAGS_WIDTH-1:0] flags; // is_compare=True, is_rand=False
  rand bit valid; // is_compare=False, is_rand=False

  // ── 物理端口字段（Driver 驱动 / Monitor 采样）──
  rand logic ready;  // output

  // ─── 内建字段 ───
  int      req_id;
  int      tag;
  bit      error;
  realtime begin_time;
  constraint passive_c { }

  function new(string name = "ALU_out_seq_item");
    super.new(name);
  endfunction
endclass : ALU_out_seq_item