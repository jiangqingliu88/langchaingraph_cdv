// Environment Package: uart_env_pkg
package uart_env_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  // 导入所有 Agent 包
  import UART_in_pkg::*;

  // 包含环境组件文件
  `include "uart_env_config.sv"
  `include "seqs/uart_env_virtual_sequencer.sv"
  `include "uart_env.sv"

endpackage : uart_env_pkg