// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_env_config.sv
//   作者:     -
//   创建时间: 2026-09-09 17:58:44
//   修改时间: 2026-09-09 17:58:44
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════



// Environment Configuration: APB_env_config
// 自动生成，不要手动修改

class APB_env_config extends uvm_object;
  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack/config_db 自动化）──
  `uvm_object_utils_begin(APB_env_config)
    `uvm_field_int(has_scoreboard, UVM_DEFAULT)
    `uvm_field_object(apb_master_cfg, UVM_DEFAULT)
    `uvm_field_object(apb_slave_cfg, UVM_DEFAULT)
  `uvm_object_utils_end

  // 是否启用 scoreboard（默认开启；仅当存在 scoreboards 时 environment 才引用）
  bit has_scoreboard = 1;

  // Agent 配置数组
  apb_master_config apb_master_cfg;
  apb_slave_config apb_slave_cfg;

  function new(string name = "APB_env_config");
    super.new(name);
    apb_master_cfg = apb_master_config::type_id::create("apb_master_cfg");
    apb_slave_cfg = apb_slave_config::type_id::create("apb_slave_cfg");
  endfunction

  // 配置有效性检查
  virtual function void check_config();
    // TODO: 实现配置合法性检查
  endfunction

endclass : APB_env_config
