// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_env_coverage.sv
//   作者:     -
//   创建时间: 2026-09-08 17:16:01
//   修改时间: 2026-09-08 17:16:01
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Env Coverage: APB_env_coverage
// 环境级功能覆盖率模型（跨 agent 的语义级 covergroup，自动生成）

// 为每个 agent 声明独立的 analysis_imp（不同 seq_item 类型）
`uvm_analysis_imp_decl(_apb_master)

class APB_env_coverage extends uvm_component;
  `uvm_component_utils(APB_env_coverage)

  // 分析端口：接收各 agent 的 monitor 采样
  uvm_analysis_imp_apb_master #(apb_master_seq_item, APB_env_coverage) apb_master_export;

  // 采样项（保存最新采样的 transaction，供 covergroup 采样）
  apb_master_seq_item apb_master_item;

  // 功能覆盖率 covergroup（从 agent transaction 字段生成）
  covergroup cg_env;
  endgroup : cg_env

  function new(string name, uvm_component parent);
    super.new(name, parent);
    apb_master_export = new("apb_master_export", this);
    cg_env = new();
  endfunction

  // write 函数：每个 agent 的 monitor 采样触发 covergroup 采样
  function void write_apb_master(apb_master_seq_item t);
    apb_master_item = t;
    cg_env.sample();
  endfunction

  // 报告功能覆盖率
  function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    `uvm_info("ENV_COV", $sformatf("功能覆盖率: %.1f%%", cg_env.get_inst_coverage()), UVM_NONE)
  endfunction

endclass : APB_env_coverage
