// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_parameters_pkg.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Agent Parameters Package: npu_sched_out_parameters_pkg
// ============================================================
// 集中管理接口/agent 参数（ADDR_WIDTH/DATA_WIDTH 等），
// 供 seq_item / config / driver / monitor 复用，避免各处硬编码。
// 注：类型别名走 <name>_typedefs_pkg（YAML typedefs），不在这里。
package npu_sched_out_parameters_pkg;
  localparam int ISSUE_UNIT_WIDTH = 3;
  localparam int ISSUE_DECISION_WIDTH = 2;
endpackage : npu_sched_out_parameters_pkg
