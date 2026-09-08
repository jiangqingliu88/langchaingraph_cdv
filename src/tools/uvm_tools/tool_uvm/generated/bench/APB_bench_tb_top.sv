// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_bench_tb_top.sv
//   作者:     -
//   创建时间: 2026-09-07 23:32:17
//   修改时间: 2026-09-07 23:32:17
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

  // ── Clock & Reset Generation ──
  reg pclk = 0;
  reg presetn = 0;
  always #5ns pclk = ~pclk;

  // ── Wire Declarations ──
  wire [31:0] paddr;
  wire [31:0] pwdata;
  wire [31:0] prdata;
  wire pwrite;
  wire psel;
  wire penable;
  wire pready;
  wire pslverr;

  // ── Continuous Assignments ──

  // ── Interface Instances ──
  // 使用 harness 时接口直接 bind 到 DUT module（见 bench/harness/*.sv），此处不再实例化

  // ── DUT Instantiation ──
  apb_slave_dut
  u_dut (
    .pclk(pclk),
    .presetn(presetn),
    .paddr(paddr),
    .pwrite(pwrite),
    .psel(psel),
    .penable(penable),
    .pwdata(pwdata),
    .prdata(prdata),
    .pready(pready),
    .pslverr(pslverr)
  );

  // ── Reference Model Compare（DUT vs 黄金参考模型，逐拍对比）──
  // 由 find_spec_yaml 按 spec 接口匹配黄金库自动接入（bench.ref_model）；
  // 端口映射（clk→pclk 等）与比对输出（prdata 等）来自黄金模型元数据。
  // 无黄金命中时该块不渲染（诚实：不假装比对）。

  // ── Reset Release（独立 initial 块，与 run_test 并行，避免 run_test 前消耗时间）──
  initial begin
    #100 presetn = ~presetn;
  end

  // ── UVM Configuration & Test Launch ──
  // 使用 harness 时 vif 由 harness.set_vifs() 在测试 build_phase 里配置，此处不再 set
  initial begin
    uvm_root::get().set_report_verbosity_level_hier(UVM_MEDIUM);
    uvm_root::get().set_timeout(10ms);
    run_test();
  end

  // ── Waveform Dump ──
  initial begin
    if ($test$plusargs("DUMP_WAVES")) begin
      $dumpfile("apb_tb_top.fst");
      $dumpvars(0, APB_bench_tb_top);
    end
  end

  // ── Simulation Control ──

endmodule : APB_bench_tb_top
