// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_loopback_test.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Loopback Test: APB_loopback_test
// ============================================================
import uvm_pkg::*;
import APB_pkg::*;
`include "uvm_macros.svh"

// 简单激励序列：随机生成 N 个 master 事务（不等待响应，规避 get_response 阻塞）
class APB_loopback_seq extends uvm_sequence #(APB_master_seq_item);
  `uvm_object_utils(APB_loopback_seq)

  int num_items = 20;

  function new(string name = "APB_loopback_seq");
    super.new(name);
  endfunction

  task body();
    repeat (num_items) begin
      APB_master_seq_item req;
      req = APB_master_seq_item::type_id::create("req");
      if (!req.randomize())
        `uvm_fatal("SEQ", "randomize failed")
      start_item(req);
      finish_item(req);
    end
  endtask
endclass : APB_loopback_seq


class APB_loopback_test extends uvm_test;
  `uvm_component_utils(APB_loopback_test)

  APB_loopback_env env_h;
  int num_items = 20;

  function new(string name = "APB_loopback_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    env_h = APB_loopback_env::type_id::create("env_h", this);
  endfunction

  task configure_phase(uvm_phase phase);
    super.configure_phase(phase);
    `uvm_info(get_type_name(), "configure_phase: start", UVM_MEDIUM)
    phase.raise_objection(this);
    phase.drop_objection(this);
  endtask

  task main_phase(uvm_phase phase);
    super.main_phase(phase);
    `uvm_info(get_type_name(), "main_phase: start", UVM_MEDIUM)
    APB_loopback_seq seq;

    phase.raise_objection(this);

    `uvm_info("LB_TEST", "Starting APB master→slave loopback test", UVM_NONE)

    // 等待复位释放
    #105ns;

    seq = APB_loopback_seq::type_id::create("seq");
    seq.num_items = num_items;
    seq.start(env_h.master_agent_h.sequencer);

    // 等待最后一项被 slave monitor 采样
    #30ns;

    `uvm_info("LB_TEST", $sformatf("Loopback test completed: %0d items sent", num_items), UVM_NONE)
    phase.drop_objection(this);
  endtask

endclass : APB_loopback_test
