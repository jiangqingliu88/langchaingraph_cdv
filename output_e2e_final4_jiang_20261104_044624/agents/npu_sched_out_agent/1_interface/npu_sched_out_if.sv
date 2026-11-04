// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_if.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Interface: npu_sched_out_if
// AXI-VIP 风格：内部 logic + master/slave/monitor 时钟块 + modport
//   dir: 'output' => master 驱动、slave 采样
//   dir: 'input'  => slave 驱动、master 采样
//
// ── 从端信号（dir: input）为什么是"wire + 影子变量"两个名字 ──
//   `<name>`      : 对外（DUT 直连在这里，master/monitor 也采样它）
//   `<name>_slv`  : TB 从端变量，**slave_cb 驱动它**（缺省高阻 'z）
//   `assign <name> = <name>_slv;`
//
// 这样每个变量**只有一个驱动源**：
//   · `<name>_slv` ← 时钟块（唯一）
//   · `<name>`     ← 那条 assign（唯一），wire 语义下 'z 会让位给强驱动
// 于是两种 bench 都能用同一份接口：
//   · DUT 直连（DUT 挂在从端）：slave agent 是 passive，从端变量始终 'z，
//     `<name>` 上只有 DUT 在驱动 → 读到的就是 DUT 的真值
//   · loopback（没有 DUT）：slave driver 写 `<name>_slv`，经 assign 送到 `<name>`
//
// 原先是"`<name>` 一个变量 + slave 时钟块直接 output 它"：只要 DUT 也直连
// `<name>`，Questa 在 vopt 阶段就判
//   "Variable '.../<name>', driven via a port connection, is multiply driven"
// —— 整个设计加载不了。而那恰恰是"从端时钟块反向驱动"最自然的写法，
// 所以不能靠把时钟块降级成"仅采样"来躲（那会让 slave driver 没法走时钟块）。
// ============================================================

interface npu_sched_out_if  (input logic clk, input logic rst_n);
import npu_sched_out_parameters_pkg::*;
  wire  issue_valid;                          // 对外（DUT 直连 / master 采样）
  logic issue_valid_slv = 'z;                 // TB 从端（slave_cb 驱动）
  wire  [3-1:0] issue_unit;   // 对外（DUT 直连 / master 采样）
  logic [3-1:0] issue_unit_slv = 'z;   // TB 从端（slave_cb 驱动）
  wire  [2-1:0] issue_decision;   // 对外（DUT 直连 / master 采样）
  logic [2-1:0] issue_decision_slv = 'z;   // TB 从端（slave_cb 驱动）

  // 从端信号路由：TB 从端不驱动时保持 'z，让位给 DUT 的强驱动
  assign issue_valid = issue_valid_slv;
  assign issue_unit = issue_unit_slv;
  assign issue_decision = issue_decision_slv;

  // -------- Master 时钟块（驱动 output，采样 input）--------
  clocking master_cb @(posedge clk);
    input  issue_valid;
    input  issue_unit;
    input  issue_decision;
  endclocking : master_cb

  // -------- Slave 时钟块（采样 output 端口，驱动 input 端口）--------
  // 方向与 master_cb **恰好相反**：master 驱动的信号这边是 `input`（采样），
  // master 采样的信号这边是 `output`（驱动）。这份给 **slave driver** 用。
  //
  // 驱动的是**从端影子变量 `<name>_slv`**（不是对外的 `<name>`）：对外的
  // `<name>` 是 wire，要留给 DUT 直连，由上面的 assign 做二选一。
  // 时钟块永远保留这些 output —— 有没有 DUT 都一样，slave driver 照常经时钟块驱动。
  clocking slave_cb @(posedge clk);
    output issue_valid_slv;
    output issue_unit_slv;
    output issue_decision_slv;
  endclocking : slave_cb

  // -------- Monitor 时钟块（仅采样）--------
  clocking mon_cb @(posedge clk);
    input  issue_valid;
    input  issue_unit;
    input  issue_decision;
  endclocking : mon_cb

  modport MASTER  (clocking master_cb, input rst_n);
  modport SLAVE   (clocking slave_cb,  input rst_n);
  modport MONITOR (clocking mon_cb,    input rst_n);


    // 接口内部获取配置对象（非常高级但合法的用法）
    //npu_sched_out_port_config cfg;
    //initial begin
    //    if (!uvm_config_db#(npu_sched_out_port_config)::get(null, "*.env.*", "cfg", cfg)) begin
    //        cfg = npu_sched_out_port_config::type_id::create("cfg");
    //    end
    //end

    // 宽松模式：高位不能是未知态（X/Z），但允许 0/1（不推荐，通常用于调试）
    //property p_addr_valid;
    //    @(posedge clk) valid |-> ($isunknown(addr[`NPU_SCHED_OUT_MAX_ADDR_WIDTH-1:cfg.addr_width]));
    //endproperty
endinterface : npu_sched_out_if
