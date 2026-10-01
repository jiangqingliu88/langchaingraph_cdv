// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     filelist.f
//   作者:     JQLIU
//   创建时间: 2026-09-12
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: jqliu@nanocorechip.com
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


# ============================================================
# apb 编译 filelist
# ============================================================
# 编译顺序：interface → system_if → pkg（pkg 内按依赖顺序 include 所有 class）
+incdir+../../../src/tools/uvm_tools/tool_uvm/base_pkg/common_typedefs
../../../src/tools/uvm_tools/tool_uvm/base_pkg/common_typedefs/common_typedefs_pkg.sv
apb_parameters_pkg.sv
apb_typedefs_pkg.sv
1_interface/apb_if.sv
1_interface/apb_system_if.sv
+incdir+.
apb_pkg.sv
