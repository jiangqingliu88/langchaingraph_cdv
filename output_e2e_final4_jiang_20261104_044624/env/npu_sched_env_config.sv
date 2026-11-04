// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_config.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════



// Environment Configuration: npu_sched_env_config
// 自动生成，不要手动修改

class npu_sched_env_config extends uvm_object;

  // 是否启用 scoreboard（默认开启；仅当存在 scoreboards 时 environment 才引用）
  bit has_scoreboard = 1;

  // Agent 配置数组
  npu_sched_in_port_config npu_sched_in_cfg;
  npu_sched_out_port_config npu_sched_out_cfg;

  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack/config_db 自动化）──
  // **必须放在字段声明之后**：这些宏展开成引用各字段的方法体，放在声明之前
  // Questa 判「Undefined variable」（实测：port_config / seq_item 都栽在这儿）。
  `uvm_object_utils_begin(npu_sched_env_config)
    `uvm_field_int(has_scoreboard, UVM_DEFAULT)
    `uvm_field_object(npu_sched_in_cfg, UVM_DEFAULT)
    `uvm_field_object(npu_sched_out_cfg, UVM_DEFAULT)
  `uvm_object_utils_end

  function new(string name = "npu_sched_env_config");
    super.new(name);
    npu_sched_in_cfg = npu_sched_in_port_config::type_id::create("npu_sched_in_cfg");
    npu_sched_in_cfg.port_kind = MASTER;
    npu_sched_out_cfg = npu_sched_out_port_config::type_id::create("npu_sched_out_cfg");
    npu_sched_out_cfg.port_kind = MASTER;
  endfunction

  // 配置有效性检查
  virtual function void check_config();
    // TODO: 实现配置合法性检查
  endfunction

endclass : npu_sched_env_config
