// Environment Package: apb_uart_env_pkg
package apb_uart_env_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  // 导入所有 Agent 包
  import apb_uart_in_pkg::*;
  import apb_uart_out_pkg::*;
`ifdef USE_SC_MODEL_CHECK
  import apb_uart_env_sc_pred_env_pkg::*;
`endif
  // 包含环境组件文件
  `include "apb_uart_env_config.sv"
  `include "seqs/apb_uart_env_virtual_sequencer.sv"
  `include "apb_uart_env.sv"

endpackage : apb_uart_env_pkg

