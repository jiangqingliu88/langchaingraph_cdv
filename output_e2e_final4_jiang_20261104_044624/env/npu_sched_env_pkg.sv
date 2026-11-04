// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_pkg.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Environment Package: npu_sched_env_pkg
package npu_sched_env_pkg;
  import uvm_pkg::*;
  import npu_sched_env_parameters_pkg::*;
  // 注：这里原来还有一句 `import npu_sched_env_typedefs_pkg::*;` ——
  // 而**没有任何模板生成这个包**。一句解析不了的 import 会让**整个 package 作废**，
  // 于是 env / tests / seqs / tb_top 全链报 "Could not find the package"，
  // 一屏连带错误，根因只是这一行。要真需要 env 级 typedef，得先补模板。
  // 公共件（base_pkg）—— 环境里用到的 `clk_rst_agent` / `in_order_scoreboard`
  // 这些类型住在这儿。不 import 的话它们全是 "Invalid type"。
  import clk_and_rst_pkg::*;
  import scb_pkg::*;
  // 公共类型别名：`MASTER` / `SLAVE` / `RESP_*` / `READ` / `WRITE` 这些枚举
  // 定义在 common_typedefs_pkg 里，env_config 直接拿它们赋 port_kind —— 不 import
  // 就是一片 "Undefined variable: 'MASTER'"。
  import common_typedefs_pkg::*;
  `include "uvm_macros.svh"
  // 导入所有 Agent 包
  //
  // **SV 的 import 不传递**：`import apb_pkg::*` 不会把 apb_typedefs_pkg 的内容
  // 一并带进来，所以 agent 的子包要各 import 一遍 —— 否则 `MASTER` / `SLAVE`
  //（port_kind_enum）、`ADDR_WIDTH` 这些在 env_config 里全是 "Undefined variable"。
  import npu_sched_in_pkg::*;
  import npu_sched_in_typedefs_pkg::*;
  import npu_sched_in_parameters_pkg::*;
  import npu_sched_out_pkg::*;
  import npu_sched_out_typedefs_pkg::*;
  import npu_sched_out_parameters_pkg::*;
  // 导入 Sub-env 包
  // 导入 VIP env 包（外部 VIP 集成）
  // 导入 Register Model 包（RAL，来自各组件 pkg 字段或 type 的 "pkg::" 前缀）
`ifdef USE_SC_MODEL_CHECK
  import npu_sched_env_sc_pred_env_pkg::*;
`endif
  // 工具组件（predictor 这些）—— 它们是**裸 class，不在任何包里**，
  // 所以只能 `include` 进来、import 不了。必须排在 config 之前：
  // env_config / env 里会声明 `apb_predictor apb_pred;` 这类成员，类型要先可见。

  // 包含环境组件文件（依赖顺序：config → virtual_sequencer → [cons] → coverage → sim_end → env）
  // 注意：scoreboard（sb_type 指定）不在此 include，通过 import 对应 package 引入。
  `include "npu_sched_env_config.sv"
  `include "seqs/npu_sched_env_virtual_sequencer.sv"
  // ── 约束策略层（**必须在 virtual_sequencer 之后**：协调序列的 p_sequencer
  //    就是它）── 以前这些文件生成了却从没被 include，连编译都没进过。
  `include "cons/npu_sched_env_coordinated_sequence.sv"
  `include "npu_sched_env_coverage.sv"
  `include "npu_sched_env_sim_end.sv"
  `include "npu_sched_env.sv"

endpackage : npu_sched_env_pkg

