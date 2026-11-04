// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_in_loopback_tb.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Loopback Testbench: npu_sched_in_loopback_tb
// ============================================================
// interface 内部 logic + modport，无需外部端口连接
//
// **`import` / `` `include `` 必须写在 module 内部**：写在外面是 $unit 作用域，
// 而 $unit 里的 import **不会**进到 module 里 —— `uvm_config_db#(...)` 会报
// "Undefined variable: 'uvm_config_db'" + "near \"#\": syntax error"。
module npu_sched_in_loopback_tb;
  `include "uvm_macros.svh"
  import uvm_pkg::*;
  import npu_sched_in_pkg::*;

  logic clk   = 0;
  logic rst_n = 0;

  // 接口实例
  //
  // **不要在这里传 `#(.ADDR_WIDTH(...))`**：生成出来的 `npu_sched_in_if` 是
  // `interface npu_sched_in_if (input logic ...);` —— **没有参数列表**，
  // 宽度是从 `npu_sched_in_parameters_pkg` import 进来的 localparam。
  // 对 localparam 做参数覆盖，vopt 直接报
  //   "(vopt-3013) A parameter override is not allowed for localparam 'ADDR_WIDTH'"
  // 整个设计加载不了。
  npu_sched_in_if npu_sched_in_if_inst (
    .clk(clk),
    .rst_n(rst_n)
  );

  // ── 这里**不再**实例化 `npu_sched_in_system_if` ──
  // 原先是留着躲 "(vsim-8451) Virtual interface resolution cannot find a matching
  // instance"：`npu_sched_in_pkg` 无条件 include 了 system_env/monitor，Questa
  // 在 load 阶段就要求有这个类型的实例。现在**没有 subenv 的构建（loopback）
  // 根本不编那几个类**（`npu_sched_in_pkg` 里用
  // `` `ifndef npu_sched_in_loop_back_test `` 挡掉，开关由 loopback 的 filelist
  // 给），类型不存在 → 这个空实例也就不需要了。

  always #5 clk = ~clk;

  initial begin
    // ── vif **按 agent 分发到 agent 级** ──
    // 不再用一句 `set(null, "*", ...)` 广播：那会把同一个句柄撒给所有层级，
    // 谁都取得到、也说不清谁该拿哪个。这里显式写死两个 agent 的路径 ——
    // 「哪个 agent 拿哪个接口」在 tb 上就是**看得见的一行**。
    //
    // **为什么两个 agent 仍共用一个接口实例**：`npu_sched_in_if` 把 master /
    // slave 两半打包在一起（`master_cb` 驱动、`slave_cb` 采样并驱动 `<sig>_slv`，
    // 接口内部 `assign <sig> = <sig>_slv`）。想给 master / slave 各例一个实例、
    // 再在外部把两个实例连起来 —— vopt 直接拒：
    //   "(vopt-12003) Variable '<sig>_slv' written by continuous and procedural
    //    assignments" → Error loading design
    // 因为每个实例的 `slave_cb`（clocking output）都在**过程性**驱动它，外部再
    // `assign` 就是连续+过程双驱动。要拆成两个实例，必须先把接口拆成 master/slave
    // 两个**类型**（`vif` 的类型写在 `npu_sched_in_port_config` 里，会级联到
    // agents / env / system_if）。
    uvm_config_db#(virtual npu_sched_in_if)::set(
        null, "*.master_agent_h*", "vif", npu_sched_in_if_inst);
    uvm_config_db#(virtual npu_sched_in_if)::set(
        null, "*.slave_agent_h*",  "vif", npu_sched_in_if_inst);
    run_test("npu_sched_in_loopback_test");
  end

  initial begin
    #100 rst_n = 1;
    #50000000 $display("LOOPBACK_TIMEOUT");
    $finish;
  end
endmodule : npu_sched_in_loopback_tb
