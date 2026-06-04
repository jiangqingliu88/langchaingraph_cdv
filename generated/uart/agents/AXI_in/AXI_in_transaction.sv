// Sequence Item: AXI_in_seq_item
// 通过 `include 引入，不包含独立 package

class AXI_in_seq_item extends uvm_sequence_item;
  `uvm_object_utils(AXI_in_seq_item)
  rand bit [31:0] addr; // is_compare=True, is_rand=True
  rand bit [31:0] data; // is_compare=True, is_rand=True
  rand bit is_write; // is_compare=True, is_rand=True

  // ── 物理端口字段（Driver 驱动 / Monitor 采样）──
  rand logic [32-1:0] awaddr;  // output
  rand logic awvalid;  // output
  rand logic awready;  // input
  rand logic [32-1:0] wdata;  // output
  rand logic wvalid;  // output
  rand logic wready;  // input
  rand logic [32-1:0] araddr;  // output
  rand logic arvalid;  // output
  rand logic arready;  // input
  rand logic [32-1:0] rdata;  // input
  rand logic rvalid;  // input
  rand logic rready;  // output

  // ─── 内建字段 ───
  int      req_id;
  int      tag;
  bit      error;
  realtime begin_time;
  constraint valid_c { data inside {[0:255]}; }

  function new(string name = "AXI_in_seq_item");
    super.new(name);
  endfunction
endclass : AXI_in_seq_item