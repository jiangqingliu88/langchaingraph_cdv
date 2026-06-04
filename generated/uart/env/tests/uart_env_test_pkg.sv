// Test Package: uart_env_test_pkg
package uart_env_test_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
    // 直接导入 Agent 包（SV import 不可传递）
  import AXI_in_pkg::*;
  import UART_in_pkg::*;
  import UART_out_pkg::*;
  // 导入 env 包
  import uart_env_pkg::*;



  // 包含环境组件文件
  `include "uart_env_base_test.sv"


endpackage : uart_env_test_pkg