

// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_env_pkg_filelist.f
//   作者:     -
//   创建时间: 2026-09-09 17:58:44
//   修改时间: 2026-09-09 17:58:44
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// UVM 编译 filelist —— 整环境 + bench + testpoint TC 一键编译（绝对路径）
// 用法: vlog -sv -f APB_env_pkg_filelist.f
// ============================================================
// DUT (项目源码)
// TODO: 填入 DUT 源码路径（替换本行）

// ─── Base PKG: Clock & Reset VIP + Scoreboard 组件族 ───
+incdir+C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\base_pkg/clk_and_rst
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\base_pkg/clk_and_rst/clk_and_rst_pkg.sv
+incdir+C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\base_pkg/scb
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\base_pkg/scb/in_order_scoreboard.svh
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\base_pkg/scb/out_of_order_scoreboard.svh
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\base_pkg/scb/typed_scoreboard.svh
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\base_pkg/scb/algorithm_scoreboard.svh

// ─── Interface & Agent Package（interface 级 agent 目录）───
+incdir+C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\agents/APB_agent
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\agents/APB_agent/1_interface/APB_if.sv
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\agents/APB_agent/1_interface/APB_system_if.sv
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\agents/APB_agent/APB_parameter_pkg.sv
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\agents/APB_agent/APB_pkg.sv

// ─── Harness（bind 式，须在 tb_top 前编译）──
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\bench/apb_harness.sv

// ─── VIP env（外部 VIP 集成，vip_path 指向 VIP 源码/incdir）──

// ─── Environment ───
+incdir+C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\env
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\env/APB_env_parameters_pkg.sv
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\env/APB_env_pkg.sv
+incdir+C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\env/tests
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\env/tests/APB_env_test_pkg.sv
+incdir+C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\env/seqs
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\env/seqs/APB_env_seq_pkg.sv

// ─── Testpoint TC（tool_testgen 产物，可选；tc_constraints 随 tc_pkg include）──
+incdir+C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\env/..
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\env/../APB_env_tc_pkg.sv

// ─── Testbench Top ───
C:\Users\liujiangqing\Desktop\cdv_advanced\src\tools\uvm_tools\tool_uvm\generated\bench/APB_bench_tb_top.sv
