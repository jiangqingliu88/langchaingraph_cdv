// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_bench_tb_top.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// Testbench Top: npu_sched_bench_tb_top
// Data-driven generated from bench YAML configuration.
`timescale 1ns/1ps
module npu_sched_bench_tb_top;
  import uvm_pkg::*;
  import npu_sched_env_test_pkg::*;

  // ── Clock & Reset Interface（clk/rst 由环境 clk_rst_agent 驱动）──
  clk_rst_if clk_vif();

  // ── 接口实例 + DUT 例化（**直连**，不走 bind 式 harness）──
  //
  // 每个 `bench.interfaces[]` 项 = 一个接口实例：
  //   · 时钟/复位接到 clk_rst_if（`.pclk(pclk_vif.clk[0])`）
  //   · 数据信号按**同名**直连 DUT 的端口（`.paddr(apb_if_inst.paddr)`）
  // —— 名字对不上就是编译不过，这比 harness 的隐式 bind 好查得多。
  npu_sched_in_if npu_sched_in_if_inst(
    .clk(clk_vif.clk[0]),
    .rst_n(clk_vif.rst_n[0])
  );
  npu_sched_out_if npu_sched_out_if_inst(
    .clk(clk_vif.clk[0]),
    .rst_n(clk_vif.rst_n[0])
  );
  // ── 系统接口实例（agent 包的 npu_sched_in_system_env / _system_monitor 引用
  //    `virtual npu_sched_in_system_if`；设计里没有它**任何实例**时，Questa load 阶段报
  //    "(vsim-8451) Virtual interface resolution cannot find a matching instance"，整个设计
  //    加载不了 —— 哪怕那些组件根本没例化。所以这里无条件实例化，并把真实接口句柄
  //    挂进 master_if / slave_if 数组（下标 0）。）──
  npu_sched_in_system_if npu_sched_in_if_sys_if_inst();
  // ── 系统接口实例（agent 包的 npu_sched_out_system_env / _system_monitor 引用
  //    `virtual npu_sched_out_system_if`；设计里没有它**任何实例**时，Questa load 阶段报
  //    "(vsim-8451) Virtual interface resolution cannot find a matching instance"，整个设计
  //    加载不了 —— 哪怕那些组件根本没例化。所以这里无条件实例化，并把真实接口句柄
  //    挂进 master_if / slave_if 数组（下标 0）。）──
  npu_sched_out_system_if npu_sched_out_if_sys_if_inst();

  npu_sched u_npu_sched (
    .clk(clk_vif.clk[0]),
    .rst_n(clk_vif.rst_n[0]),
    .instr_valid(npu_sched_in_if_inst.instr_valid),
    .instr_opcode(npu_sched_in_if_inst.instr_opcode),
    .instr_type(npu_sched_in_if_inst.instr_type),
    .instr_dtype(npu_sched_in_if_inst.instr_dtype),
    .instr_tile_id(npu_sched_in_if_inst.instr_tile_id),
    .instr_src_addr(npu_sched_in_if_inst.instr_src_addr),
    .instr_dst_addr(npu_sched_in_if_inst.instr_dst_addr),
    .barrier_type(npu_sched_in_if_inst.barrier_type),
    .op_priority(npu_sched_in_if_inst.op_priority),
    .issue_valid(npu_sched_out_if_inst.issue_valid),
    .issue_unit(npu_sched_out_if_inst.issue_unit),
    .issue_decision(npu_sched_out_if_inst.issue_decision)
  );

  // ── vif 广播给 agent ──
  // `agent_path` 是**实例路径**（如 apb_master_agent_h），用 `*.<path>*` 匹配，
  // 这样 env 挂在哪个层级都找得到。环境侧再从 config_db 取出来塞进 agent 的 cfg.vif。
  initial begin
    uvm_config_db#(virtual npu_sched_in_if)::set(null, "*.npu_sched_in_agent_h*", "vif", npu_sched_in_if_inst);
    uvm_config_db#(virtual npu_sched_out_if)::set(null, "*.npu_sched_out_agent_h*", "vif", npu_sched_out_if_inst);
    // 时钟复位接口：**只有 tb_top 能实例化它**，所以由这里放进 config_db，
    // env 取出来再转发给 clk_rst agent（env 自己例化不了接口）。
    uvm_config_db#(virtual clk_rst_if)::set(null, "*", "clk_vif", clk_vif);
    // 系统接口：本 bench 把同一个接口实例同时挂到 master 侧与 slave 侧的第 0 槽
    //（agent 包的系统 env 是按 `sys_vif.master_if[i]` / `slave_if[i]` 取句柄的）。
    npu_sched_in_if_sys_if_inst.master_if[0] = npu_sched_in_if_inst;
    npu_sched_in_if_sys_if_inst.slave_if[0]  = npu_sched_in_if_inst;
    uvm_config_db#(virtual npu_sched_in_system_if)::set(null, "*", "sys_vif", npu_sched_in_if_sys_if_inst);
    // 系统接口：本 bench 把同一个接口实例同时挂到 master 侧与 slave 侧的第 0 槽
    //（agent 包的系统 env 是按 `sys_vif.master_if[i]` / `slave_if[i]` 取句柄的）。
    npu_sched_out_if_sys_if_inst.master_if[0] = npu_sched_out_if_inst;
    npu_sched_out_if_sys_if_inst.slave_if[0]  = npu_sched_out_if_inst;
    uvm_config_db#(virtual npu_sched_out_system_if)::set(null, "*", "sys_vif", npu_sched_out_if_sys_if_inst);
    // ── DUT 覆盖率接口 ──
    // 它**不是这里例化的**：`bind npu_sched npu_sched_cov_if` 把它放进了
    // DUT 的作用域（那是唯一能让**内部信号**连进来的地方 —— 内部名在 DUT 里，
    // tb_top 这一层看不见）。所以层次路径 = `<DUT 实例>.<bind 实例名>`。
    //
    // 路径两段都来自 env_cov_bins.yaml 的 `dut_if`（类型名/实例名）与 bench
    // （DUT 实例名）—— 与覆盖率组件是**同一份来源**，不会各说各话。
    uvm_config_db#(virtual npu_sched_cov_if)::set(
        null, "*", "cov_vif", u_npu_sched.u_npu_sched_cov_if);
  end

  // ── 波形名 + 日志时间单位 ──
  initial begin
    // **UVM 报告行的时间单位在这里定。**
    // UVM 的报告服务器组消息时是 `$swrite(time_str, "%0t", $time)`
    //（uvm_report_server.svh），而 `%t` 的显示格式完全由 `$timeformat` 决定。
    // 不设的话打印的是**裸数字**：
    //     UVM_INFO ... @ 15035000: uvm_test_top ...
    // —— 看不出那是 ps 还是 ns（本 bench 的 timescale 是 1ns/1ps，
    // 15035000 其实是 15035ns = 15.035us）。设成 ns 后是：
    //     UVM_INFO ... @ 15035.000 ns: uvm_test_top ...
    // 参数: (时间单位指数, 小数位, 单位后缀, 最小字段宽)；-9 = ns。
    // **必须在 run_test() 之前**：报告服务器第一次组消息就取当前的时间格式。
    $timeformat(-9, 3, " ns", 15);
    run_test();
  end



endmodule : npu_sched_bench_tb_top
