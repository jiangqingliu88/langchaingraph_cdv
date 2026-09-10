// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     apb_harness.sv
//   作者:     -
//   创建时间: 2026-09-09 17:58:44
//   修改时间: 2026-09-09 17:58:44
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// UVM Harness: apb_harness（bind 式自连接）
//   各 interface 分别 bind 到目标 module（按 module 名，所有实例生效）
// ============================================================


// ── 2) dummy interface: set_vifs() 把每个 vif 配置进环境 agent ──
interface apb_harness();
// ── 1) 各 interface 实例化在 harness 内（信号在 harness bind 的 DUT 作用域里解析）──
      apb_interface apb_if(.pclk(pclk), .presetn(presetn), .paddr(paddr), .pwrite(pwrite), .psel(psel), .penable(penable), .pwdata(pwdata), .prdata(prdata), .pready(pready), .pslverr(pslverr));

  function void set_vifs(string path);
    uvm_config_db#(virtual apb_interface)::set(null, {path, ".apb_master_agent_h.*"}, "vif", apb_if);
  endfunction
  // ── force/release 控制（apb_if_force_en 置 1 时把 DUT 信号 force 成接口信号）──
  logic apb_if_force_en = 0;
  always @(*) begin
    if (apb_if_force_en) begin  // put force_en ctrl bit in interface
      force pclk = apb_if.pclk;
      force presetn = apb_if.presetn;
      force paddr = apb_if.paddr;
      force pwrite = apb_if.pwrite;
      force psel = apb_if.psel;
      force penable = apb_if.penable;
      force pwdata = apb_if.pwdata;
      force prdata = apb_if.prdata;
      force pready = apb_if.pready;
      force pslverr = apb_if.pslverr;
    end
    else begin
      release pclk;
      release presetn;
      release paddr;
      release pwrite;
      release psel;
      release penable;
      release pwdata;
      release prdata;
      release pready;
      release pslverr;
    end
  end

endinterface : apb_harness

// ── 3) 把 harness 本身 bind 到目标 module ──
bind apb_slave_dut apb_harness harness();
