import uvm_pkg::*;
import ALU_in_pkg::*;
`include "uvm_macros.svh"

// === Agent Loopback Test: ALU_in ===
// 发送 N 个随机 item，验证 Driver→Monitor 闭环数据一致性

class ALU_in_loopback_test extends uvm_test;
  `uvm_component_utils(ALU_in_loopback_test)

  ALU_in_loopback_env env_h;
  int num_items = 20;

  function new(string name = "ALU_in_loopback_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    env_h = ALU_in_loopback_env::type_id::create("env_h", this);
  endfunction

  task run_phase(uvm_phase phase);
    ALU_in_seq_item item;
    ALU_in_base_seq  seq;

    phase.raise_objection(this);

    // 创建并启动随机 Sequence
    seq = ALU_in_base_seq::type_id::create("seq");
    // seq 默认发送 10 个随机事务，可通过 send_random_transactions(count) 重载

    `uvm_info("LB_TEST", $sformatf("Starting loopback test"), UVM_NONE)

    seq.start(env_h.agent_h.sqr);

    // 等待所有 item 被收集
    #2000;

    phase.drop_objection(this);
    `uvm_info("LB_TEST", "Loopback test completed", UVM_NONE)
  endtask

endclass : ALU_in_loopback_test
