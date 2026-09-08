// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_pkg.sv
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
// Agent Package: APB_pkg
// ============================================================
// 注意：APB_if.sv（interface）须在 package 之前单独编译（见 filelist）
package APB_pkg;
  import uvm_pkg::*;
  import APB_parameter_pkg::*;
  `include "uvm_macros.svh"

  `include "2_config/APB_master_config.sv"
  `include "2_config/APB_slave_config.sv"
  `include "3_transaction_sequencer/APB_master_seq_item.sv"
  `include "3_transaction_sequencer/APB_slave_seq_item.sv"
  `include "3_transaction_sequencer/APB_master_sequencer.sv"
  `include "3_transaction_sequencer/APB_slave_sequencer.sv"
  `include "4_driver_monitor/APB_master_driver.sv"
  `include "4_driver_monitor/APB_slave_driver.sv"
  `include "4_driver_monitor/APB_master_monitor.sv"
  `include "4_driver_monitor/APB_slave_monitor.sv"
  `include "5_agent/APB_master_agent.sv"
  `include "5_agent/APB_slave_agent.sv"
  `include "5_agent/APB_system_config.sv"
  `include "5_agent/APB_system_env.sv"
  `include "7_sequence/APB_master_sequence.sv"
  `include "7_sequence/APB_slave_sequence.sv"
  `include "8_ral/APB_reg_adapter.sv"

endpackage : APB_pkg
