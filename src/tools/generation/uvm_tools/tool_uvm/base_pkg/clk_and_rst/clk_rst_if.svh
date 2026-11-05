// ════════════════════════════════════════════════════════════════
// clk_rst_if.svh —— 时钟复位接口（NUM_CLKS/NUM_RSTS 可参数化）
// 职责: clk/rst_n/clk_gate/rst_active/clk_running 信号 + cb 时钟块 + mp modport
// 注: 形参名 NUM_CLKS/NUM_RSTS 与旧宏同名会互相展开（编译错误），
//   宏已改名为 CLK_RST_NUM_CLKS / CLK_RST_NUM_RSTS（见 clk_and_rst_pkg.sv）
// 依赖: 无
// ════════════════════════════════════════════════════════════════

`ifndef CLK_RST_IF_SVH
`define CLK_RST_IF_SVH

// ── 2. Interface ──
interface clk_rst_if #(
  parameter int NUM_CLKS = 1,
  parameter int NUM_RSTS = 1
)();
  logic [NUM_CLKS-1:0] clk;
  logic [NUM_RSTS-1:0] rst_n;
  logic [NUM_CLKS-1:0] clk_gate;
  logic [NUM_RSTS-1:0] rst_active;
  logic [NUM_CLKS-1:0] clk_running;
  clocking cb @(posedge clk[0]);
    input rst_n;
  endclocking
  modport mp (input clk, rst_n, output clk_gate);
endinterface : clk_rst_if

`endif // CLK_RST_IF_SVH
