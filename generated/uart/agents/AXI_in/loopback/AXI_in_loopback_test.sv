import uvm_pkg::*;
import AXI_in_pkg::*;
`include "uvm_macros.svh"

// === Agent Loopback Test: AXI_in ===
// 发送 N 个随机 item，验证 Driver→Monitor 闭环数据一致性

class AXI_in_loopback_test extends uvm_test;
  `uvm_component_utils(AXI_in_loopback_test)

  AXI_in_loopback_env env_h;
  int num_items = 20;

  function new(string name = "AXI_in_loopback_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    env_h = AXI_in_loopback_env::type_id::create("env_h", this);
  endfunction

  task run_phase(uvm_phase phase);
    AXI_in_seq_item item;
    AXI_in_base_seq  seq;

    phase.raise_objection(this);

    // 创建并启动随机 Sequence
    seq = AXI_in_base_seq::type_id::create("seq");
    seq.num_transactions = num_items;

    `uvm_info("LB_TEST", $sformatf("Starting loopback: %0d items", num_items), UVM_NONE)

    fork
      seq.start(env_h.agent_h.sqr);
    join

    // 等待所有 item 被收集
    #10000;

    phase.drop_objection(this);
    `uvm_info("LB_TEST", "Loopback test completed", UVM_NONE)
  endtask

endclass : AXI_in_loopback_test
