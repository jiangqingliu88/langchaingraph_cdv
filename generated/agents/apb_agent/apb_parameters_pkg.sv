// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_parameters_pkg.sv
//   作者:     JQLIU
//   创建时间: 2026-09-12
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: jqliu@nanocorechip.com
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Agent Parameters Package: apb_parameters_pkg
// ============================================================
// 集中管理接口/agent 参数（ADDR_WIDTH/DATA_WIDTH 等），
// 供 seq_item / config / driver / monitor 复用，避免各处硬编码。
// 注：类型别名走 <name>_typedefs_pkg（YAML typedefs），不在这里。
package apb_parameters_pkg;
  localparam int ADDR_WIDTH = 32;
  localparam int DATA_WIDTH = 32;
endpackage : apb_parameters_pkg
