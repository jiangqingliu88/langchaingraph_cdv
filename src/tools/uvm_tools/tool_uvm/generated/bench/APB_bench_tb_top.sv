// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_bench_tb_top.sv
//   作者:     -
//   创建时间: 2026-09-09 17:58:44
//   修改时间: 2026-09-09 17:58:44
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Testbench Top: APB_bench_tb_top
// Data-driven generated from bench YAML configuration.
`timescale 1ns/1ps
module APB_bench_tb_top;
  import uvm_pkg::*;
  import APB_env_test_pkg::*;

  // ── Clock & Reset Interface（clk/rst 由环境 clk_rst_agent 驱动）──
  clk_rst_if pclk_vif();

  // ── DUT 实例化（模块名来自 harness.bind_to；clk/rst 端口接 clk_rst_if，
  //   harness 的 bind 连接点即 DUT 模块内部同名信号，端口被驱动后 apb_if 自然拿到时钟/复位）──
  apb_slave_dut u_dut (
    .pclk(pclk_vif.clk[0]),
    .presetn(pclk_vif.rst_n[0])
  );


  initial begin
    run_test();
  end

endmodule : APB_bench_tb_top
