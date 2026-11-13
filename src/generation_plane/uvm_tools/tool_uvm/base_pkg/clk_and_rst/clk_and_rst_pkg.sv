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

// ── 接口留在 $unit ──
// interface 不能放进 package，而下面那些类要 `virtual clk_rst_if` ——
// 所以它必须在包**外面**先声明。Questa 允许包内引用 $unit 的接口（实测过）。
`include "clk_rst_if.svh"

// ════════════════════════════════════════════════════════════════
// **为什么这里必须有 `package`**
//
// 这个文件一直**没有** package 声明 —— 它只是把一堆 .svh 在 `$unit` 作用域里
// include 进来。于是外部 `import clk_and_rst_pkg::*` 找不到这个包，而 `$unit`
// 的作用域**对 package 内部不可见**。结果：环境包里写
//     clk_rst_agent pclk_clk_rst_agent_h;
// 永远报 "Invalid type 'clk_rst_agent'" —— 而文件名叫 `_pkg`，看名字谁都以为
// 它是个包。实测踩过：这一处让整个 env 编不过，连带错误铺满一屏，
// 根因只是少了两行。
// ════════════════════════════════════════════════════════════════
package clk_and_rst_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "clk_rst_config.svh"
  `include "clk_rst_event.svh"
  `include "clk_driver.svh"
  `include "rst_driver.svh"
  `include "clk_rst_monitor.svh"
  `include "clk_rst_sequence.svh"
  `include "clk_rst_agent.svh"
endpackage : clk_and_rst_pkg
