// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     apb_harness.sv
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// UVM Harness: apb_harness（bind 式自连接）
//   style: bind（bind — 接口分别 bind + 向上查找；
//          inside — 接口实例化在 harness 内，只 bind harness 一次）
//   使用: 测试 build_phase 里调用 <harness 层级路径>.set_vifs(env.get_full_name());
// ============================================================
// ── 1) 各 interface bind 到目标 module（module 名 → 所有实例生效）──
bind apb_slave_dut apb_interface apb_if(.pclk(pclk), .presetn(presetn), .paddr(paddr), .pwrite(pwrite), .psel(psel), .penable(penable), .pwdata(pwdata), .prdata(prdata), .pready(pready), .pslverr(pslverr));
// ── 2) dummy interface: set_vifs() 把每个 vif 配置进环境 agent ──
interface apb_harness();

  function void set_vifs(string path);
    uvm_config_db#(virtual apb_interface)::set(null, {path, ".apb_master_agent_h.*"}, "vif", apb_slave_dut.apb_if);
  endfunction
endinterface : apb_harness

// ── 3) 把 harness 本身 bind 到目标 module ──
bind apb_slave_dut apb_harness harness();
