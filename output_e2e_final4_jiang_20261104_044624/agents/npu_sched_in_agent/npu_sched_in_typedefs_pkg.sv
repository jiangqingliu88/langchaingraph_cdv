// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_in_typedefs_pkg.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Agent Typedef Package: npu_sched_in_typedefs_pkg
// ============================================================
// interface 级类型别名（YAML typedefs: 名字 → 类型），
// 供 seq_item / config / driver / monitor 复用，避免各处硬编码。
// 注：import 参数包，类型里才能引用 parameters（如 bit [ADDR_WIDTH-1:0]）；
//     引用另一个 typedef 时被引用者必须写在前面（声明顺序 = YAML 顺序）。
package npu_sched_in_typedefs_pkg;
  import npu_sched_in_parameters_pkg::*;

endpackage : npu_sched_in_typedefs_pkg
