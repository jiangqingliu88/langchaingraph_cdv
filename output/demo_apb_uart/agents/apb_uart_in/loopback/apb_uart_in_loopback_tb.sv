// === Agent Loopback Testbench: apb_uart_in ===
// 单 Agent 自测顶层 —— 独立编译运行，无需完整 env
// 编译时需 +define+apb_uart_in_loop_back_test（filelist 中已添加）

`include "uvm_macros.svh"
import uvm_pkg::*;
import apb_uart_in_pkg::*;

module apb_uart_in_loopback_tb;
  reg clk   = 0;
  reg rst_n = 0;
  localparam int DATA_WIDTH = 32;
  wire [DATA_WIDTH-1:0] data;
  wire valid;
  wire ready;

  // 接口实例
  apb_uart_in_interface #(
    .DATA_WIDTH(32)
  ) apb_uart_in_if (
    .clk(clk),
    .rst(rst_n)
   ,.data(data)
   ,.valid(valid)
   ,.ready(ready)
  );

  // ── Loopback wiring: auto-pair inputs←outputs by name pattern, rest tied to 0 ──















  assign ready = '0;

  always #5 clk = ~clk;

  initial begin
    // 设置 virtual interface
    uvm_config_db #(virtual apb_uart_in_interface)::set(null, "*", "vif", apb_uart_in_if);
    // 启动测试
    run_test("apb_uart_in_loopback_test");
  end

  initial begin
    #100 rst_n = 1;
    #500000 $display("LOOPBACK_TIMEOUT");
    $finish;
  end
endmodule : apb_uart_in_loopback_tb
