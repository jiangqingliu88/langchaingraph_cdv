// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_master_config.sv
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
// Master Config: APB_master_config
// ============================================================

class APB_master_config extends uvm_object;
  `uvm_object_utils(APB_master_config)

  // 公共协议参数
  int addr_width = 32;
  int data_width = 32;
  int id_width   = 4;

  // 模式控制（由 interface YAML is_active.master 决定）
  uvm_active_passive_enum is_active = UVM_ACTIVE;

  // 错误注入公共开关
  int error_injection_rate = 0; // 0~100

  // 虚拟接口句柄（由 TB 传入）
  virtual APB_if vif;

  // ── Master 专属 ──
  // 驱动延迟（背压控制）
  int drive_delay_min = 0;
  int drive_delay_max = 0;

  // Outstanding 与乱序（预留接口）
  int max_outstanding          = 8;
  bit enable_out_of_order_resp = 1;

  // 超时检测
  int response_timeout   = 100;
  bit timeout_raise_error = 1;

  function new(string name = "APB_master_config");
    super.new(name);
  endfunction

  function string convert2string();
    string s = super.convert2string();
    s = {s, $sformatf("\n  role: MASTER")};
    s = {s, $sformatf("\n  active: %s", is_active.name())};
    s = {s, $sformatf("\n  addr_width: %0d", addr_width)};
    s = {s, $sformatf("\n  data_width: %0d", data_width)};
    s = {s, $sformatf("\n  error_injection_rate: %0d%%", error_injection_rate)};
    return s;
  endfunction
endclass : APB_master_config
