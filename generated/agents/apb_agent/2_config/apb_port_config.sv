// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_port_config.sv
//   作者:     JQLIU
//   创建时间: 2026-09-12
//   修改时间: 2026-09-15 15:43:52
//   联系邮箱: jqliu@nanocorechip.com
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════



// ============================================================
// Port Config: apb_port_config
// ============================================================
class apb_port_config extends uvm_object;
  // ── file 注册机制：字段注册进 factory（copy/compare/print/pack/config_db 自动化）──
  `uvm_object_utils_begin(apb_port_config)
    `uvm_field_int(addr_width, UVM_DEFAULT)
    `uvm_field_int(data_width, UVM_DEFAULT)
    `uvm_field_int(id_width, UVM_DEFAULT)
    `uvm_field_enum(uvm_active_passive_enum, is_active, UVM_DEFAULT)
    `uvm_field_enum(port_kind_enum, port_kind, UVM_DEFAULT)
    `uvm_field_int(error_injection_rate, UVM_DEFAULT)
    // vif: virtual interface，UVM field 宏不支持注册（由 config_db 传递）
    `uvm_field_int(drive_delay_min, UVM_DEFAULT)
    `uvm_field_int(drive_delay_max, UVM_DEFAULT)
    `uvm_field_int(max_outstanding, UVM_DEFAULT)
    `uvm_field_int(enable_out_of_order_resp, UVM_DEFAULT)
    `uvm_field_int(response_timeout, UVM_DEFAULT)
    `uvm_field_int(timeout_raise_error, UVM_DEFAULT)
    `uvm_field_enum(response_mode_e, response_mode, UVM_DEFAULT)
    `uvm_field_int(memory_size, UVM_DEFAULT)
    `uvm_field_int(memory_start_addr, UVM_DEFAULT)
    `uvm_field_int(memory_end_addr, UVM_DEFAULT)
    `uvm_field_int(default_read_data, UVM_DEFAULT)
    `uvm_field_aa_int_int_unsigned(memory, UVM_DEFAULT)
    `uvm_field_int(response_delay_min, UVM_DEFAULT)
    `uvm_field_int(response_delay_max, UVM_DEFAULT)
    `uvm_field_int(enable_out_of_order, UVM_DEFAULT)
    `uvm_field_aa_int_string(id_delay_map, UVM_DEFAULT)
    `uvm_field_int(error_addr_start, UVM_DEFAULT)
    `uvm_field_int(error_addr_end, UVM_DEFAULT)
    `uvm_field_enum(resp_type_e, force_resp_type, UVM_DEFAULT)
    `uvm_field_int(priority_a, UVM_DEFAULT)
  `uvm_object_utils_end

  // 公共协议参数,driver mask, // 核心：运行期动态截断，只驱动有效位宽
  // 工业界的标准做法就是：接口（vif）和事务（Transaction）的物理位宽，agent parameters 都统一取整个系统所支持的最大位宽（MAX_WIDTH）。
  int addr_width = 32;
  int data_width = 32;
  int id_width   = 4;

  // 模式控制（缺省 UVM_ACTIVE；由 env 级 agents[].is_active / loopback 套件按实例赋值）
  uvm_active_passive_enum is_active = UVM_ACTIVE;

  // 端口类型（MASTER = 驱动侧实例，SLAVE = 响应侧实例；monitor/scoreboard 按此分支）
  port_kind_enum port_kind = MASTER;

  // 错误注入公共开关
  int error_injection_rate = 0; // 0~100

  // 虚拟接口句柄（由 TB 传入）
  virtual apb_if vif;

  // ── Master 侧（驱动侧）──
  // 驱动延迟（背压控制）
  int drive_delay_min = 0;
  int drive_delay_max = 0;

  // Outstanding 与乱序（预留接口）
  int max_outstanding          = 8;
  bit enable_out_of_order_resp = 1;

  // 超时检测
  int response_timeout   = 100;
  bit timeout_raise_error = 1;


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
  int id_delay_map[string];

  // 错误注入（特定地址窗口）
  bit [31:0] error_addr_start = 32'h0000_0000;
  bit [31:0] error_addr_end   = 32'h0000_0000;
  resp_type_e force_resp_type = RESP_RANDOM;
  rand int priority_a;
  constraint c_priority_range { priority_a inside {[0:15]}; }

  function new(string name = "apb_port_config");
    super.new(name);
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
endclass : apb_port_config
