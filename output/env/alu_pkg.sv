// Environment Package: alu_pkg
package alu_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  // 导入所有 Agent 包
  import ALU_in_pkg::*;
  import ALU_out_pkg::*;
`ifdef USE_SC_MODEL_CHECK
  import alu_sc_pred_env_pkg::*;
`endif
  // 包含环境组件文件
  `include "alu_config.sv"
  `include "seqs/alu_virtual_sequencer.sv"
  `include "alu.sv"

endpackage : alu_pkg

