// Sequence Item: UART_in_seq_item
// 通过 `include 引入，不包含独立 package

class UART_in_seq_item extends uvm_sequence_item;
  `uvm_object_utils(UART_in_seq_item)
  rand bit [7:0] data; // is_compare=True, is_rand=True
  rand bit [1:0] parity; // is_compare=True, is_rand=True
  rand bit [1:0] stop_bits; // is_compare=True, is_rand=True
  rand int baud_rate; // is_compare=True, is_rand=True

  // ── 物理端口字段（Driver 驱动 / Monitor 采样）──
  rand logic tx;  // output
  rand logic rx;  // input
  rand logic [4-1:0] interrupt;  // output

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