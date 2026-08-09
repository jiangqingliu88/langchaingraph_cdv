// Test Package: apb_uart_env_test_pkg
package apb_uart_env_test_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
    // 直接导入 Agent 包（SV import 不可传递）
  import apb_uart_in_pkg::*;
  import apb_uart_out_pkg::*;
  // 导入 env 包
  import apb_uart_env_pkg::*;



  // 包含环境组件文件
  `include "apb_uart_env_base_test.sv"


endpackage : apb_uart_env_test_pkg