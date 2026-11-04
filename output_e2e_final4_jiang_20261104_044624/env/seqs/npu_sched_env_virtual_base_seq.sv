// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_virtual_base_seq.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Virtual Base Sequence: npu_sched_env_virtual_base_seq
// 增强版 - 支持仲裁、同步、超时控制

class npu_sched_env_virtual_base_seq extends uvm_sequence;
  `uvm_object_utils(npu_sched_env_virtual_base_seq)

  npu_sched_env_config cfg;
  protected int m_started = 0;
  protected int m_completed = 0;
  
  // pragma custom field_decl begin
  // pragma custom field_decl end

  function new(string name = "npu_sched_env_virtual_base_seq");
    super.new(name);
  endfunction

  virtual task pre_body();
    if (!uvm_config_db#(npu_sched_env_config)::get(get_sequencer(), "", "cfg", cfg))
      `uvm_fatal("VSEQ_CFG", "Config not set")
  endtask

  virtual task body();
    `uvm_info("VSEQ", "Virtual base seq body - override in derived", UVM_MEDIUM)
  endtask
  protected task start_npu_sched_in_sequence(uvm_sequence #(npu_sched_in_master_seq_item) _s);
    m_started++;
    fork
      _s.start(get_sequencer());
    join_none
  endtask

  protected task send_npu_sched_in_random(int count = 1);
    npu_sched_in_master_sequence _rs;
    _rs = npu_sched_in_master_sequence::type_id::create("_rs");
    _rs.num_transactions = count;
    start_npu_sched_in_sequence(_rs);
  endtask
  protected task start_npu_sched_out_sequence(uvm_sequence #(npu_sched_out_master_seq_item) _s);
    m_started++;
    fork
      _s.start(get_sequencer());
    join_none
  endtask

  protected task send_npu_sched_out_random(int count = 1);
    npu_sched_out_master_sequence _rs;
    _rs = npu_sched_out_master_sequence::type_id::create("_rs");
    _rs.num_transactions = count;
    start_npu_sched_out_sequence(_rs);
  endtask

  // pragma custom seq_body begin
  // pragma custom seq_body end

endclass : npu_sched_env_virtual_base_seq
