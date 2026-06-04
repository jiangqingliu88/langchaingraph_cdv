// === Agent Loopback Testbench: UART_in ===
// 单 Agent 自测顶层 —— 独立编译运行，无需完整 env

`include "uvm_macros.svh"
import uvm_pkg::*;
import UART_in_pkg::*;

module UART_in_loopback_tb;
  reg clk   = 0;
  reg rst_n = 0;

  // 接口实例
  UART_in_interface #(
    .DATA_WIDTH(32)
  ) UART_in_if (.pclk(clk), .presetn(rst_n));

  always #5 clk = ~clk;

  initial begin
    // 设置 virtual interface
    uvm_config_db #(virtual UART_in_interface)::set(null, "*", "vif", UART_in_if);
    // 启动测试
    run_test("UART_in_loopback_test");
  end

  initial begin
    #100 rst_n = 1;
    #500000 $display("LOOPBACK_TIMEOUT");
    $finish;
  end
endmodule : UART_in_loopback_tb
