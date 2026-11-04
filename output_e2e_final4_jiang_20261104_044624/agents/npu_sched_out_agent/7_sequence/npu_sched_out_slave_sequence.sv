// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_slave_sequence.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Slave Sequence: npu_sched_out_slave_sequence
// ============================================================
// ★ 事件驱动：从 Sequencer FIFO 取 Monitor 抓到的请求，生成响应

class npu_sched_out_slave_sequence extends uvm_sequence #(npu_sched_out_slave_seq_item);
  `uvm_object_utils(npu_sched_out_slave_sequence)
  `uvm_declare_p_sequencer(npu_sched_out_slave_sequencer)

  protected bit [7:0] memory [bit [31:0]];

  function new(string name = "npu_sched_out_slave_sequence");
    super.new(name);
  endfunction
  virtual task pre_body();
  endtask
  virtual task body();
    npu_sched_out_slave_seq_item req_resp;
    npu_sched_out_port_config cfg;
    // 1. 向 p_sequencer 请求配置，存入 cfg
    p_sequencer.get_cfg(cfg);
    if (cfg == null)
      `uvm_error(get_type_name(), "Sequencer cfg is null (agent build 未传入 config_db)")
    forever begin
      // ★ 从 Sequencer FIFO 取 Monitor 抓到的请求
      p_sequencer.req_fifo.get(req_resp);

      if (req_resp.xact_type == READ)
        handle_read(req_resp);
      else
        handle_write(req_resp);

      start_item(req_resp);
      finish_item(req_resp);
    end
  endtask
  virtual task post_body();
  endtask
  virtual function void handle_write(npu_sched_out_slave_seq_item req);
    // 写内存：addr/data 字段由 YAML transaction_vars 决定，LLM 可按协议扩展
    bit status = req.randomize() with {
      delay_cycles inside {[0:5]};
      force_resp == 2'b00;
    };
    if (!status) `uvm_fatal("SEQ", "Randomize failed")
  endfunction

  virtual function void handle_read(npu_sched_out_slave_seq_item req);
    bit status = req.randomize() with {
      delay_cycles inside {[0:3]};
      force_resp == 2'b00;
    };
    if (!status) `uvm_fatal("SEQ", "Randomize failed")
  endfunction

  function void write_mem(bit [31:0] addr, byte data[]);
    foreach (data[i]) memory[addr + i] = data[i];
  endfunction

  // pragma custom seq_body begin
  // pragma custom seq_body end
endclass : npu_sched_out_slave_sequence
