// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_parameter_pkg.sv
//   作者:     -
//   创建时间: 2026-09-07 23:32:17
//   修改时间: 2026-09-07 23:32:17
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Agent Parameter Package: APB_parameter_pkg
// ============================================================
// 集中管理接口/agent 参数（ADDR_WIDTH/DATA_WIDTH 等），
// 供 seq_item / config / driver / monitor 复用，避免各处硬编码。
package APB_parameter_pkg;
  localparam int ADDR_WIDTH = 32;
  localparam int DATA_WIDTH = 32;
endpackage : APB_parameter_pkg
