// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_master_sequence.sv
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
// Master Sequence: APB_master_sequence
// ============================================================

class APB_master_sequence extends uvm_sequence #(APB_master_seq_item);
  `uvm_object_utils(APB_master_sequence)

  function new(string name = "APB_master_sequence");
    super.new(name);
  endfunction

  task do_write();
    APB_master_seq_item req = APB_master_seq_item::type_id::create("req");
    start_item(req);
    assert(req.randomize() with { xact_type == WRITE; });
    finish_item(req);
    get_response(req);
  endtask

  task do_read();
    APB_master_seq_item req = APB_master_seq_item::type_id::create("req");
    start_item(req);
    assert(req.randomize() with { xact_type == READ; });
    finish_item(req);
    get_response(req);
  endtask

  // pragma custom seq_body begin
  // pragma custom seq_body end
endclass : APB_master_sequence
