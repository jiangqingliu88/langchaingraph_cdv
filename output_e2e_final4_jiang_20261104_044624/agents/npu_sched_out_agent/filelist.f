// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     filelist.f
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


# ============================================================
# npu_sched_out 编译 filelist
# ============================================================
# 编译顺序：interface → system_if → pkg（pkg 内按依赖顺序 include 所有 class）
+incdir+../../../src/tools/generation/uvm_tools/tool_uvm/base_pkg/common_typedefs
../../../src/tools/generation/uvm_tools/tool_uvm/base_pkg/common_typedefs/common_typedefs_pkg.sv
npu_sched_out_parameters_pkg.sv
npu_sched_out_typedefs_pkg.sv
1_interface/npu_sched_out_if.sv
1_interface/npu_sched_out_system_if.sv
+incdir+.
npu_sched_out_pkg.sv
