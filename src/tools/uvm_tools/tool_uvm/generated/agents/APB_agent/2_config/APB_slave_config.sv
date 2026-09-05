// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_slave_config.sv
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
// Slave Config: APB_slave_config
// ============================================================

class APB_slave_config extends uvm_object;
  `uvm_object_utils(APB_slave_config)

  // 公共协议参数
  int addr_width = 32;
  int data_width = 32;
  int id_width   = 4;

  // 模式控制（由 interface YAML is_active.slave 决定）
  uvm_active_passive_enum is_active = UVM_ACTIVE;

  // 错误注入公共开关
  int error_injection_rate = 0; // 0~100

  // 虚拟接口句柄（由 TB 传入）
  virtual APB_if vif;

  // ── Slave 专属 ──
  // 响应模式
  typedef enum {AUTO_MEMORY, SEQUENCER_DRIVEN, ERROR_INJECTION} response_mode_e;
  response_mode_e response_mode = SEQUENCER_DRIVEN;

  // 内存模型参数
  int memory_size = 1024 * 1024;
  bit [31:0] memory_start_addr = 32'h0000_0000;
  bit [31:0] memory_end_addr   = 32'h000F_FFFF;
  byte unsigned default_read_data = 8'h0;
  // 内存数组（AUTO_MEMORY 响应模式：写存、读取，协议默认驱动逻辑使用）
  bit [31:0] memory[bit [31:0]];

  // 响应延迟
  int response_delay_min = 0;
  int response_delay_max = 5;

  // 乱序与 Outstanding（预留接口）
  bit enable_out_of_order = 0;
  int max_outstanding = 8;
  int id_delay_map[string];

  // 错误注入（特定地址窗口）
  bit [31:0] error_addr_start = 32'h0000_0000;
  bit [31:0] error_addr_end   = 32'h0000_0000;
  typedef enum {RESP_RANDOM=0, RESP_OKAY=1, RESP_ERROR=2, RESP_DECERR=3} resp_type_e;
  resp_type_e force_resp_type = RESP_RANDOM;

  function new(string name = "APB_slave_config");
    super.new(name);
  endfunction

  function string convert2string();
    string s = super.convert2string();
    s = {s, $sformatf("\n  role: SLAVE")};
    s = {s, $sformatf("\n  active: %s", is_active.name())};
    s = {s, $sformatf("\n  addr_width: %0d", addr_width)};
    s = {s, $sformatf("\n  data_width: %0d", data_width)};
    s = {s, $sformatf("\n  error_injection_rate: %0d%%", error_injection_rate)};
    return s;
  endfunction

  function bit is_addr_in_error_window(bit [31:0] addr);
    if (error_addr_start == 0 && error_addr_end == 0) return 0;
    return (addr >= error_addr_start && addr <= error_addr_end);
  endfunction

  function bit [1:0] get_random_resp(bit [31:0] addr);
    if (force_resp_type == RESP_RANDOM) begin
      return $urandom_range(0, 3);
    end else if (force_resp_type == RESP_ERROR) begin
      return 2'b10;
    end else if (force_resp_type == RESP_DECERR) begin
      return 2'b11;
    end else begin
      if (is_addr_in_error_window(addr) && $urandom() % 100 < error_injection_rate)
        return 2'b10;
      return 2'b00;
    end
  endfunction
endclass : APB_slave_config
