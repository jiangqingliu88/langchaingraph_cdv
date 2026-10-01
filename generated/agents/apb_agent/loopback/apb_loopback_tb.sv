// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_loopback_tb.sv
//   作者:     JQLIU
//   创建时间: 2026-09-12
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: jqliu@nanocorechip.com
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Loopback Testbench: apb_loopback_tb
// ============================================================
// interface 内部 logic + modport，无需外部端口连接
`include "uvm_macros.svh"
import uvm_pkg::*;
import apb_pkg::*;

module apb_loopback_tb;
  logic clk   = 0;
  logic rst_n = 0;

  // 接口实例
  apb_if #(
    .ADDR_WIDTH(32),
    .DATA_WIDTH(32)
  ) apb_if_inst (
    .pclk(clk),
    .presetn(rst_n)
  );

  always #5 clk = ~clk;

  initial begin
    uvm_config_db#(virtual apb_if)::set(null, "*", "vif", apb_if_inst);
    run_test("apb_loopback_test");
  end

  initial begin
    #100 rst_n = 1;
    #50000000 $display("LOOPBACK_TIMEOUT");
    $finish;
  end
endmodule : apb_loopback_tb
