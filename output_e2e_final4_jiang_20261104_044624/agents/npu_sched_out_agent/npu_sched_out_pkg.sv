// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_pkg.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Agent Package: npu_sched_out_pkg
// ============================================================
// 注意：npu_sched_out_if.sv（interface）须在 package 之前单独编译（见 filelist）
package npu_sched_out_pkg;
  import uvm_pkg::*;
  import npu_sched_out_parameters_pkg::*;
  import npu_sched_out_typedefs_pkg::*;
  import common_typedefs_pkg::*;
  `include "uvm_macros.svh"
  // 最大物理位宽（编译期固定）
  `define NPU_SCHED_OUT_MAX_ADDR_WIDTH 512
  `define NPU_SCHED_OUT_MAX_DATA_WIDTH 512
  `define NPU_SCHED_OUT_AXI_MAX_ID_WIDTH 16
  //  requirements
  `include "2_config/npu_sched_out_port_config.sv"
  `include "3_transaction_sequencer/npu_sched_out_base_seq_item.sv"
  `include "3_transaction_sequencer/npu_sched_out_master_seq_item.sv"
  `include "3_transaction_sequencer/npu_sched_out_slave_seq_item.sv"
  `include "3_transaction_sequencer/npu_sched_out_master_sequencer.sv"
  `include "3_transaction_sequencer/npu_sched_out_slave_sequencer.sv"
  `include "4_driver_monitor/npu_sched_out_master_driver.sv"
  `include "4_driver_monitor/npu_sched_out_slave_driver.sv"
  `include "4_driver_monitor/npu_sched_out_port_monitor.sv"
  `include "5_agent/npu_sched_out_master_agent.sv"
  `include "5_agent/npu_sched_out_slave_agent.sv"

  // ── 系统（sub）env 只在**有 subenv** 的构建里编 ──
  // loopback 构建没有 subenv，却因为这一段无条件 include，被 Questa 在 load 阶段
  // 要求实例化 `virtual npu_sched_out_system_if`：
  //   "(vsim-8451) Virtual interface resolution cannot find a matching instance"
  // → "Error loading design"（实测删掉 tb 里那个实例就是 4 条这个错）。
  // 所以由 filelist 的 `+define+npu_sched_out_loop_back_test`
  // （`src/tools/lib/filelist.py:build_loopback_filelist` 加的）作开关：
  // loopback 不编这几个类 → 类型都不存在 → tb 里也就不需要那个空实例。
  `ifndef npu_sched_out_loop_back_test
  `include "5_agent/npu_sched_out_system_config.sv"
  `include "5_agent/npu_sched_out_system_vsqr.sv"
  `include "5_agent/npu_sched_out_system_monitor.sv"
  `include "5_agent/npu_sched_out_system_env.sv"
  `endif

  `include "7_sequence/npu_sched_out_master_sequence.sv"
  `include "7_sequence/npu_sched_out_slave_sequence.sv"
  `include "8_ral/npu_sched_out_reg_adapter.sv"

endpackage : npu_sched_out_pkg
