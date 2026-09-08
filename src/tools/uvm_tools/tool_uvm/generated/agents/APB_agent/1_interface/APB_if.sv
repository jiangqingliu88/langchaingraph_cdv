// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_if.sv
//   作者:     -
//   创建时间: 2026-09-07 23:32:17
//   修改时间: 2026-09-07 23:32:17
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Interface: APB_if
// AXI-VIP 风格：内部 logic + master/slave/monitor 时钟块 + modport
//   dir: 'output' => master 驱动、slave 采样
//   dir: 'input'  => slave 驱动、master 采样
// ============================================================

interface APB_if #(
  parameter int ADDR_WIDTH = 32,
  parameter int DATA_WIDTH = 32
) (input logic pclk, input logic presetn);
  logic [ADDR_WIDTH-1:0] paddr;  // output
  logic pwrite;                         // output
  logic psel;                         // output
  logic penable;                         // output
  logic [DATA_WIDTH-1:0] pwdata;  // output
  logic [DATA_WIDTH-1:0] prdata;  // input
  logic pready;                         // input
  logic pslverr;                         // input

  // -------- Master 时钟块（驱动 output，采样 input）--------
  clocking master_cb @(posedge pclk);
    output paddr;
    output pwrite;
    output psel;
    output penable;
    output pwdata;
    input  prdata;
    input  pready;
    input  pslverr;
  endclocking : master_cb

  // -------- Slave 时钟块（采样 input，驱动 output）--------
  clocking slave_cb @(posedge pclk);
    input  paddr;
    input  pwrite;
    input  psel;
    input  penable;
    input  pwdata;
    output prdata;
    output pready;
    output pslverr;
  endclocking : slave_cb

  // -------- Monitor 时钟块（仅采样）--------
  clocking mon_cb @(posedge pclk);
    input  paddr;
    input  pwrite;
    input  psel;
    input  penable;
    input  pwdata;
    input  prdata;
    input  pready;
    input  pslverr;
  endclocking : mon_cb

  modport MASTER  (clocking master_cb, input presetn);
  modport SLAVE   (clocking slave_cb,  input presetn);
  modport MONITOR (clocking mon_cb,    input presetn);

endinterface : APB_if
