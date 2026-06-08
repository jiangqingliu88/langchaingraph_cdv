// === Agent Loopback Testbench: ALU_out ===
// 单 Agent 自测顶层 —— 独立编译运行，无需完整 env

`include "uvm_macros.svh"
import uvm_pkg::*;
import ALU_out_pkg::*;

module ALU_out_loopback_tb;
  reg clk   = 0;
  reg rst_n = 0;

  // 接口实例
  ALU_out_interface #(
    .DATA_WIDTH(32),
    .FLAGS_WIDTH(4),
    .ALU_OP_WIDTH(4)
  ) ALU_out_if (.clk(clk), .rst(rst_n));

  always #5 clk = ~clk;

  initial begin
    // 设置 virtual interface
    uvm_config_db #(virtual ALU_out_interface)::set(null, "*", "vif", ALU_out_if);
    // 启动测试
    run_test("ALU_out_loopback_test");
  end

  initial begin
    #100 rst_n = 1;
    #500000 $display("LOOPBACK_TIMEOUT");
    $finish;
  end
endmodule : ALU_out_loopback_tb
