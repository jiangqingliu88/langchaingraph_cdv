// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_loopback_tb.sv
//   作者:     -
//   创建时间: 2026-09-09 17:58:44
//   修改时间: 2026-09-09 17:58:44
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Loopback Testbench: APB_loopback_tb
// ============================================================
// interface 内部 logic + modport，无需外部端口连接
`include "uvm_macros.svh"
import uvm_pkg::*;
import APB_pkg::*;

module APB_loopback_tb;
  logic clk   = 0;
  logic rst_n = 0;

  // 接口实例
  APB_if #(
    .ADDR_WIDTH(32),
    .DATA_WIDTH(32)
  ) APB_if_inst (
    .pclk(clk),
    .presetn(rst_n)
  );

  always #5 clk = ~clk;

  initial begin
    uvm_config_db#(virtual APB_if)::set(null, "*", "vif", APB_if_inst);
    run_test("APB_loopback_test");
  end

  initial begin
    #100 rst_n = 1;
    #50000000 $display("LOOPBACK_TIMEOUT");
    $finish;
  end
endmodule : APB_loopback_tb
