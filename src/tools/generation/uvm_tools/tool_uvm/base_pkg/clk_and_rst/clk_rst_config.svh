// ════════════════════════════════════════════════════════════════
// clk_rst_config.svh —— 时钟复位 VIP 配置类
// 职责: 周期/占空比/抖动/门控（时钟侧）、极性/断言恢复周期（复位侧）
// 依赖: 无（在 clk_and_rst_pkg.sv 内 include）
// ════════════════════════════════════════════════════════════════

`ifndef CLK_RST_CONFIG_SVH
`define CLK_RST_CONFIG_SVH

// ── 1. Config ──
class clk_rst_config extends uvm_object;
  `uvm_object_utils(clk_rst_config)
  real    clk_period_ps    = 10000;
  real    clk_duty_cycle   = 50;
  bit     clk_start_value  = 0;
  real    clk_jitter_ps    = 0;
  int     clk_stop_after   = 0;
  bit     rst_active_low   = 1;
  int     rst_assert_cycles = 10;
  int     rst_recover_cycles = 5;
  bit     rst_start_value  = 0;
  bit     enable_clock_gating = 0;
  int     clock_gate_cycles   = 100;
  int     clock_ungate_cycles = 10;
  function new(string name = "clk_rst_config");
    super.new(name);
  endfunction
endclass : clk_rst_config

`endif // CLK_RST_CONFIG_SVH
