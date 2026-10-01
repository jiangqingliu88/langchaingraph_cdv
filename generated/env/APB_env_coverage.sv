// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     APB_env_coverage.sv
//   作者:     JQLIU
//   创建时间: 2026-09-12
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: jqliu@nanocorechip.com
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Env Coverage: APB_env_coverage
// 环境级功能覆盖率模型（跨 agent 的语义级 covergroup，自动生成）

// 为每个 agent 声明独立的 analysis_imp（不同 seq_item 类型）
`uvm_analysis_imp_decl(_apb_master)
`uvm_analysis_imp_decl(_apb_slave)

class APB_env_coverage extends uvm_component;
  `uvm_component_utils(APB_env_coverage)

  // 分析端口：接收各 agent 的 monitor 采样
  uvm_analysis_imp_apb_master #(apb_master_seq_item, APB_env_coverage) apb_master_export;
  uvm_analysis_imp_apb_slave #(apb_slave_seq_item, APB_env_coverage) apb_slave_export;

  // 采样项（保存最新采样的 transaction，供 covergroup 采样）
  apb_master_seq_item apb_master_item;
  apb_slave_seq_item apb_slave_item;

  // 功能覆盖率 covergroup（从 agent transaction 字段生成）
  covergroup cg_env;
    // coverpoint: apb_master.paddr
    cp_apb_master_paddr: coverpoint apb_master_item.paddr;
    // coverpoint: apb_master.pwrite
    cp_apb_master_pwrite: coverpoint apb_master_item.pwrite;
    // coverpoint: apb_master.pwdata
    cp_apb_master_pwdata: coverpoint apb_master_item.pwdata;
    // coverpoint: apb_slave.paddr
    cp_apb_slave_paddr: coverpoint apb_slave_item.paddr;
    // coverpoint: apb_slave.pwrite
    cp_apb_slave_pwrite: coverpoint apb_slave_item.pwrite;
    // coverpoint: apb_slave.pwdata
    cp_apb_slave_pwdata: coverpoint apb_slave_item.pwdata;
    // cross: apb_master 的关键信号组合（语义级）
    cross_apb_master: cross cp_apb_master_paddr, cp_apb_master_pwrite;
    // cross: apb_slave 的关键信号组合（语义级）
    cross_apb_slave: cross cp_apb_slave_paddr, cp_apb_slave_pwrite;
    // 语义 cross（env YAML coverage_crosses: [paddr, pwrite]）
    cr_yaml_0: cross cp_apb_master_paddr, cp_apb_master_pwrite;
  endgroup : cg_env

  function new(string name, uvm_component parent);
    super.new(name, parent);
    apb_master_export = new("apb_master_export", this);
    apb_slave_export = new("apb_slave_export", this);
    cg_env = new();
  endfunction

  // write 函数：每个 agent 的 monitor 采样触发 covergroup 采样
  function void write_apb_master(apb_master_seq_item t);
    apb_master_item = t;
    cg_env.sample();
  endfunction
  function void write_apb_slave(apb_slave_seq_item t);
    apb_slave_item = t;
    cg_env.sample();
  endfunction

  // 报告功能覆盖率
  function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    `uvm_info("ENV_COV", $sformatf("功能覆盖率: %.1f%%", cg_env.get_inst_coverage()), UVM_NONE)
  endfunction

endclass : APB_env_coverage
