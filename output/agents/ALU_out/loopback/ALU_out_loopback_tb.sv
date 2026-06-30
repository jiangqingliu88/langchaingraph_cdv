// === Agent Loopback Testbench: ALU_out ===
// 单 Agent 自测顶层 —— 独立编译运行，无需完整 env
// 编译时需 +define+ALU_out_loop_back_test（filelist 中已添加）

`include "uvm_macros.svh"
import uvm_pkg::*;
import ALU_out_pkg::*;

module ALU_out_loopback_tb;
  reg clk   = 0;
  reg rst_n = 0;
  localparam int DATA_WIDTH = 32;
  localparam int FLAGS_WIDTH = 4;
  localparam int ALU_OP_WIDTH = 4;
  wire [DATA_WIDTH-1:0] result;
  wire [FLAGS_WIDTH-1:0] flags;
  wire valid;
  wire ready;

  // 接口实例
  ALU_out_interface #(
    .DATA_WIDTH(32),
    .FLAGS_WIDTH(4),
    .ALU_OP_WIDTH(4)
  ) ALU_out_if (
    .clk(clk),
    .rst(rst_n)
   ,.result(result)
   ,.flags(flags)
   ,.valid(valid)
   ,.ready(ready)
  );

  // ── Loopback wiring: auto-pair inputs←outputs by name pattern, rest tied to 0 ──







  assign result = '0;







  assign flags = '0;







  assign valid = '0;

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
