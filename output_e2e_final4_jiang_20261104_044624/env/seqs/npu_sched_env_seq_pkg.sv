// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_seq_pkg.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Seq Package: npu_sched_env_seq_pkg
package npu_sched_env_seq_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
    // 直接导入 Agent 包（SV import 不可传递）
    //
    // 用 `agent.interface`（协议名，如 apb）而**不是** `agent.name`
    //（实例名，如 apb_master）—— 真实的包叫 `apb_pkg`。这里原来写的是 agent.name，
    // 于是生成 `import apb_master_pkg::*`：一个不存在的包，seq 全编不过。
  import npu_sched_in_pkg::*;
  import npu_sched_in_typedefs_pkg::*;
  import npu_sched_in_parameters_pkg::*;
  import npu_sched_out_pkg::*;
  import npu_sched_out_typedefs_pkg::*;
  import npu_sched_out_parameters_pkg::*;
  // 导入 env 包
  import npu_sched_env_pkg::*;


  // 包含环境组件文件
  `include "npu_sched_env_virtual_base_seq.sv"


endpackage : npu_sched_env_seq_pkg
