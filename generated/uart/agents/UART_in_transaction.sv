// Sequence Item: UART_in_seq_item
// 通过 `include 引入，不包含独立 package

class UART_in_seq_item extends uvm_sequence_item;
  `uvm_object_utils(UART_in_seq_item)
  rand bit [7:0] data; // is_compare=True, is_rand=True

  // ─── 内建字段 ───
  int      req_id;
  int      tag;
  bit      error;
  realtime begin_time;
  constraint valid_c { data inside {[0:255]}; }

  function new(string name = "UART_in_seq_item");
    super.new(name);
  endfunction
endclass : UART_in_seq_item