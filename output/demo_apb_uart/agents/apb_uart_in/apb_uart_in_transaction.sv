// Sequence Item: apb_uart_in_seq_item

class apb_uart_in_seq_item extends uvm_sequence_item;
  rand bit [DATA_WIDTH-1:0] data; // is_compare=True, is_rand=True

  // ─── 内建字段 ───
  int      req_id;
  int      tag;
  bit      error;
  realtime begin_time;

  // ─── Field Registration ───
  `uvm_object_utils_begin(apb_uart_in_seq_item)
    `uvm_field_int(data, UVM_ALL_ON)
    `uvm_field_int(req_id, UVM_ALL_ON)
    `uvm_field_int(tag, UVM_ALL_ON)
    `uvm_field_int(error, UVM_ALL_ON)
    `uvm_field_real(begin_time, UVM_ALL_ON)
  `uvm_object_utils_end
  constraint valid_c {{ data inside {{[0:255]}}; }}

  function new(string name = "apb_uart_in_seq_item");
    super.new(name);
  endfunction
endclass : apb_uart_in_seq_item