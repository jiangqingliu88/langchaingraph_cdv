



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_env_pkg_filelist.f
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// UVM 编译 filelist —— 整环境 + bench + testpoint TC 一键编译
// 用法: source Sourceme          # 定义 $WORK_PATH = 当前目录
//       vlog -sv -f npu_sched_env_pkg_filelist.f
// 路径一律以 $WORK_PATH 为根（而非生成时刻的绝对路径），故整目录可整体搬迁、
// 换机器不必重新生成。
// ============================================================
// DUT (项目源码)
// TODO: 填入 DUT 源码路径（替换本行）

// ─── Base PKG: Clock & Reset VIP + Scoreboard 组件族 + 公共类型 ───
+incdir+$WORK_PATH/../src/tools/generation/uvm_tools/tool_uvm/base_pkg/clk_and_rst
$WORK_PATH/../src/tools/generation/uvm_tools/tool_uvm/base_pkg/clk_and_rst/clk_and_rst_pkg.sv
+incdir+$WORK_PATH/../src/tools/generation/uvm_tools/tool_uvm/base_pkg/scb
$WORK_PATH/../src/tools/generation/uvm_tools/tool_uvm/base_pkg/scb/scb_pkg.sv
+incdir+$WORK_PATH/../src/tools/generation/uvm_tools/tool_uvm/base_pkg/common_typedefs
$WORK_PATH/../src/tools/generation/uvm_tools/tool_uvm/base_pkg/common_typedefs/common_typedefs_pkg.sv

// ─── Interface & Agent Package（interface 级 agent 目录）───
+incdir+$WORK_PATH/agents/npu_sched_in_agent
$WORK_PATH/agents/npu_sched_in_agent/1_interface/npu_sched_in_if.sv
$WORK_PATH/agents/npu_sched_in_agent/1_interface/npu_sched_in_system_if.sv
$WORK_PATH/agents/npu_sched_in_agent/npu_sched_in_parameters_pkg.sv
$WORK_PATH/agents/npu_sched_in_agent/npu_sched_in_typedefs_pkg.sv
$WORK_PATH/agents/npu_sched_in_agent/npu_sched_in_pkg.sv
+incdir+$WORK_PATH/agents/npu_sched_out_agent
$WORK_PATH/agents/npu_sched_out_agent/1_interface/npu_sched_out_if.sv
$WORK_PATH/agents/npu_sched_out_agent/1_interface/npu_sched_out_system_if.sv
$WORK_PATH/agents/npu_sched_out_agent/npu_sched_out_parameters_pkg.sv
$WORK_PATH/agents/npu_sched_out_agent/npu_sched_out_typedefs_pkg.sv
$WORK_PATH/agents/npu_sched_out_agent/npu_sched_out_pkg.sv

// ─── Harness（bind 式，须在 tb_top 前编译）──

// ─── VIP env（外部 VIP 集成，vip_path 指向 VIP 源码/incdir）──

// ─── Environment ───
+incdir+$WORK_PATH/env
$WORK_PATH/env/npu_sched_env_parameters_pkg.sv
// env_pkg 里 `include "utils/<name>_util.sv"`（工具组件/参考模型）**不需要**
// `+incdir+$WORK_PATH/env/utils` —— `include` 是**相对 include**：先按"包含这条
// 指令的文件所在目录"解析，而 env_pkg.sv 就在 `$WORK_PATH/env/` 下，于是
// `utils/x_util.sv` 直接落到 `$WORK_PATH/env/utils/x_util.sv`。实测 vlog 通过
// （真不存在的路径会响亮报 "Cannot open include file"）。**别好心加一句
// `+incdir+env/utils`** —— 它不解决问题，只会让"哪条路径才是权威"多一个来源。
$WORK_PATH/env/npu_sched_env_pkg.sv
+incdir+$WORK_PATH/env/tests
$WORK_PATH/env/tests/npu_sched_env_test_pkg.sv
+incdir+$WORK_PATH/env/seqs
$WORK_PATH/env/seqs/npu_sched_env_seq_pkg.sv

// ─── Testpoint TC（tool_testgen 产物，可选；tc_constraints 随 tc_pkg include）──
+incdir+$WORK_PATH/env/..
$WORK_PATH/env/../npu_sched_env_tc_pkg.sv

// ─── Testbench Top ───
$WORK_PATH/bench/npu_sched_bench_tb_top.sv
