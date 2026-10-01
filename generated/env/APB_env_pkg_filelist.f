

// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_env_pkg_filelist.f
//   作者:     -
//   创建时间: 2026-09-15 15:43:52
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// UVM 编译 filelist —— 整环境 + bench + testpoint TC 一键编译
// 用法: source Sourceme          # 定义 $WORK_PATH = 当前目录
//       vlog -sv -f APB_env_pkg_filelist.f
// 路径一律以 $WORK_PATH 为根（而非生成时刻的绝对路径），故整目录可整体搬迁、
// 换机器不必重新生成。
// ============================================================
// DUT (项目源码)
// TODO: 填入 DUT 源码路径（替换本行）

// ─── Base PKG: Clock & Reset VIP + Scoreboard 组件族 + 公共类型 ───
+incdir+$WORK_PATH/../src/tools/uvm_tools/tool_uvm/base_pkg/clk_and_rst
$WORK_PATH/../src/tools/uvm_tools/tool_uvm/base_pkg/clk_and_rst/clk_and_rst_pkg.sv
+incdir+$WORK_PATH/../src/tools/uvm_tools/tool_uvm/base_pkg/scb
$WORK_PATH/../src/tools/uvm_tools/tool_uvm/base_pkg/scb/scb_pkg.sv
+incdir+$WORK_PATH/../src/tools/uvm_tools/tool_uvm/base_pkg/common_typedefs
$WORK_PATH/../src/tools/uvm_tools/tool_uvm/base_pkg/common_typedefs/common_typedefs_pkg.sv

// ─── Interface & Agent Package（interface 级 agent 目录）───
+incdir+$WORK_PATH/agents/apb_agent
$WORK_PATH/agents/apb_agent/1_interface/apb_if.sv
$WORK_PATH/agents/apb_agent/1_interface/apb_system_if.sv
$WORK_PATH/agents/apb_agent/apb_parameters_pkg.sv
$WORK_PATH/agents/apb_agent/apb_typedefs_pkg.sv
$WORK_PATH/agents/apb_agent/apb_pkg.sv

// ─── Harness（bind 式，须在 tb_top 前编译）──
$WORK_PATH/bench/apb_harness.sv

// ─── VIP env（外部 VIP 集成，vip_path 指向 VIP 源码/incdir）──

// ─── Environment ───
+incdir+$WORK_PATH/env
$WORK_PATH/env/APB_env_parameters_pkg.sv
$WORK_PATH/env/APB_env_pkg.sv
+incdir+$WORK_PATH/env/tests
$WORK_PATH/env/tests/APB_env_test_pkg.sv
+incdir+$WORK_PATH/env/seqs
$WORK_PATH/env/seqs/APB_env_seq_pkg.sv

// ─── Testpoint TC（tool_testgen 产物，可选；tc_constraints 随 tc_pkg include）──
+incdir+$WORK_PATH/env/..
$WORK_PATH/env/../APB_env_tc_pkg.sv

// ─── Testbench Top ───
$WORK_PATH/bench/APB_bench_tb_top.sv
