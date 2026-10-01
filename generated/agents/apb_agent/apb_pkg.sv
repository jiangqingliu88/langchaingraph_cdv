// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_pkg.sv
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
// Agent Package: apb_pkg
// ============================================================
// 注意：apb_if.sv（interface）须在 package 之前单独编译（见 filelist）
package apb_pkg;
  import uvm_pkg::*;
  import apb_parameters_pkg::*;
  import apb_typedefs_pkg::*;
  import common_typedefs_pkg::*;
  `include "uvm_macros.svh"
  // 最大物理位宽（编译期固定）
  `define APB_MAX_ADDR_WIDTH 512
  `define APB_MAX_DATA_WIDTH 512
  `define APB_AXI_MAX_ID_WIDTH 16
  //  requirements
  `include "2_config/apb_port_config.sv"
  `include "3_transaction_sequencer/apb_base_seq_item.sv"
  `include "3_transaction_sequencer/apb_master_seq_item.sv"
  `include "3_transaction_sequencer/apb_slave_seq_item.sv"
  `include "3_transaction_sequencer/apb_master_sequencer.sv"
  `include "3_transaction_sequencer/apb_slave_sequencer.sv"
  `include "4_driver_monitor/apb_master_driver.sv"
  `include "4_driver_monitor/apb_slave_driver.sv"
  `include "4_driver_monitor/apb_port_monitor.sv"
  `include "5_agent/apb_master_agent.sv"
  `include "5_agent/apb_slave_agent.sv"
  `include "5_agent/apb_system_config.sv"
  `include "5_agent/apb_system_vsqr.sv"
  `include "5_agent/apb_system_monitor.sv"
  `include "5_agent/apb_system_env.sv"
  `include "7_sequence/apb_master_sequence.sv"
  `include "7_sequence/apb_slave_sequence.sv"
  `include "8_ral/apb_reg_adapter.sv"

endpackage : apb_pkg
