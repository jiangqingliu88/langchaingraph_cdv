// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_env_pkg.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Environment Package: APB_env_pkg
package APB_env_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  // 导入所有 Agent 包
  import apb_master_pkg::*;
  // 导入 Sub-env 包
  import apb_system_env_pkg::*;
  // 导入 Register Model 包（RAL，来自各组件 pkg 字段或 type 的 "pkg::" 前缀）
`ifdef USE_SC_MODEL_CHECK
  import APB_env_sc_pred_env_pkg::*;
`endif
  // 包含环境组件文件（依赖顺序：config → virtual_sequencer → coverage → env）
  // 注意：外部类 scoreboard（sb_type 指定）/ analysis 组件不在此 include，
  // 通过 import 对应 package 引入；生成式 scoreboard（mode 指定）在此 include。
  `include "APB_env_config.sv"
  `include "seqs/APB_env_virtual_sequencer.sv"
  `include "APB_env_coverage.sv"
  `include "APB_env.sv"

endpackage : APB_env_pkg

