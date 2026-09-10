// ════════════════════════════════════════════════════════════════
// clk_and_rst_pkg.sv —— 时钟复位 VIP（顶层组装文件）
// 职责: 按依赖顺序 include 各分片（.svh），对外保持本文件名不变
//   （filelist 只需编译本文件，分片经 +incdir 解析）
// 分片:
//   clk_rst_config.svh    配置类
//   clk_rst_if.svh        时钟复位接口（可参数化）
//   clk_rst_event.svh     事件枚举 + 事务
//   clk_driver.svh        时钟驱动器
//   rst_driver.svh        复位驱动器
//   clk_rst_monitor.svh   时钟复位监视器
//   clk_rst_sequence.svh  基类序列
//   clk_rst_agent.svh     Agent（cfg 广播 + 三组件例化）
// 注: 宏 CLK_RST_NUM_CLKS / CLK_RST_NUM_RSTS 控制驱动/监视通道数
//   （原 NUM_CLKS/NUM_RSTS 与 interface 形参同名会互相展开，已改名）
// ════════════════════════════════════════════════════════════════

`include "uvm_macros.svh"
import uvm_pkg::*;

`ifndef CLK_RST_NUM_CLKS
  `define CLK_RST_NUM_CLKS 1
`endif
`ifndef CLK_RST_NUM_RSTS
  `define CLK_RST_NUM_RSTS 1
`endif

`include "clk_rst_config.svh"
`include "clk_rst_if.svh"
`include "clk_rst_event.svh"
`include "clk_driver.svh"
`include "rst_driver.svh"
`include "clk_rst_monitor.svh"
`include "clk_rst_sequence.svh"
`include "clk_rst_agent.svh"
