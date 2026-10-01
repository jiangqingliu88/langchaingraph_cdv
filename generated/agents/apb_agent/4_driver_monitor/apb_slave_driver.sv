// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   nanocorechip.com NPU IP TEAM（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI. All rights reserved.
// 
//   文件:     apb_slave_driver.sv
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
// Slave Driver Callback: apb_slave_driver_cb
// ============================================================
// UVM callback 扩展点：可在响应前后插入行为（改响应数据、注入 pslverr、
// 调整延迟），**无需改动 driver 本体**。
//
// 注册（test 的 build_phase）：
//   apb_slave_driver_cb cb;
//   cb = apb_slave_driver_cb::type_id::create("cb");
//   uvm_callbacks#(apb_slave_driver,
//                  apb_slave_driver_cb)::add(drv, cb);
//
// 注：typedef class 是前置声明 —— callback 方法签名要用到 driver 类型，
//     而 driver 定义在下方（SystemVerilog 要求先声明后使用）。

typedef class apb_slave_driver;

class apb_slave_driver_cb extends uvm_callback;
  `uvm_object_utils(apb_slave_driver_cb)

  function new(string name = "apb_slave_driver_cb");
    super.new(name);
  endfunction

  // 响应前：可修改 rsp 字段（响应数据、错误位、延迟）
  virtual task pre_drive(apb_slave_driver drv,
                         apb_slave_seq_item rsp);
  endtask

  // 响应后：时序记录 / 协议检查
  virtual task post_drive(apb_slave_driver drv,
                          apb_slave_seq_item rsp);
  endtask
endclass : apb_slave_driver_cb

// ============================================================
// Slave Driver: apb_slave_driver
// ============================================================

class apb_slave_driver extends uvm_driver #(apb_slave_seq_item);
  `uvm_component_utils(apb_slave_driver)
  // 建立 driver 类型 ↔ callback 类型的回调池（uvm_do_callbacks 依赖它）
  `uvm_register_cb(apb_slave_driver, apb_slave_driver_cb)

  virtual apb_if vif;
  apb_port_config cfg;
  // pragma custom field_decl begin
  // pragma custom field_decl end

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual apb_if)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Virtual interface not set")
    if (!uvm_config_db#(apb_port_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Config not set")
    // pragma custom build_logic begin
    // pragma custom build_logic end
  endfunction

  task configure_phase(uvm_phase phase);
    super.configure_phase(phase);
    `uvm_info(get_type_name(), "configure_phase: start", UVM_MEDIUM)
    phase.raise_objection(this);
    phase.drop_objection(this);
  endtask

  task main_phase(uvm_phase phase);
    super.main_phase(phase);
    `uvm_info(get_type_name(), "main_phase: start", UVM_MEDIUM)
    // driver 的 forever 循环不 raise objection（避免悬挂）；复位门控后才开始响应
    wait (vif.presetn == 1'b1);
    forever begin
      apb_slave_seq_item rsp;
      seq_item_port.get_next_item(rsp);
      drive_response(rsp);
      seq_item_port.item_done();
    end
  endtask

  virtual task drive_response(apb_slave_seq_item rsp);
    // 回调：响应前（可改 rsp）
    `uvm_do_callbacks(apb_slave_driver, apb_slave_driver_cb,
                      pre_drive(this, rsp))
    // pragma custom drive_logic begin
    // 响应延迟（由 slave sequence 决定）
    repeat (rsp.delay_cycles) @(vif.slave_cb);
    // 默认：将请求字段回填到 slave 驱动的 input 端口
    @(vif.slave_cb);
    vif.slave_cb.prdata <= rsp.prdata;
    vif.slave_cb.pslverr <= rsp.pslverr;
    // pragma custom drive_logic end
    // 回调：响应后
    `uvm_do_callbacks(apb_slave_driver, apb_slave_driver_cb,
                      post_drive(this, rsp))
  endtask
endclass : apb_slave_driver
