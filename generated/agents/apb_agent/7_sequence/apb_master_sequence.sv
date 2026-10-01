// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_master_sequence.sv
//   作者:     JQLIU
//   创建时间: 2026-09-12
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: jqliu@nanocorechip.com
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Master Sequence: apb_master_sequence
// ============================================================

class apb_master_sequence extends uvm_sequence #(apb_master_seq_item);
  `uvm_object_utils(apb_master_sequence)
  `uvm_declare_p_sequencer(apb_master_sequencer)

  function new(string name = "apb_master_sequence");
    super.new(name);
  endfunction
  virtual task pre_body();
  endtask

  virtual task body();
    apb_port_config cfg;
    // 1. 向 p_sequencer 请求配置，存入 cfg
    p_sequencer.get_cfg(cfg);
    if (cfg == null)
      `uvm_error(get_type_name(), "Sequencer cfg is null (agent build 未传入 config_db)")
  endtask
  virtual task post_body();
  endtask
  task do_write();
    apb_master_seq_item req = apb_master_seq_item::type_id::create("req");
    start_item(req);
    assert(req.randomize() with { xact_type == WRITE; });
    finish_item(req);
    get_response(req);
  endtask

  task do_read();
    apb_master_seq_item req = apb_master_seq_item::type_id::create("req");
    start_item(req);
    assert(req.randomize() with { xact_type == READ; });
    finish_item(req);
    get_response(req);
  endtask

  // pragma custom seq_body begin
  // pragma custom seq_body end
endclass : apb_master_sequence
