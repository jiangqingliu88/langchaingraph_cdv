// Sequence Item: UART_out_seq_item
// 通过 `include 引入，不包含独立 package

class UART_out_seq_item extends uvm_sequence_item;
  `uvm_object_utils(UART_out_seq_item)
  rand bit [7:0] data; // is_compare=True, is_rand=False
  rand bit [3:0] status; // is_compare=True, is_rand=False

  // ─── 内建字段 ───
  int      req_id;
  int      tag;
  bit      error;
  realtime begin_time;
  constraint valid_c { data inside {[0:255]}; }

  function new(string name = "UART_out_seq_item");
    super.new(name);
  endfunction
endclass : UART_out_seq_item