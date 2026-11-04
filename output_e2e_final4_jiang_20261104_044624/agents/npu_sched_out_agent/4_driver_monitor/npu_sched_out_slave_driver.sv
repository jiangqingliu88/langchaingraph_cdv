// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_slave_driver.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Slave Driver Callback: npu_sched_out_slave_driver_cb
// ============================================================
// UVM callback 扩展点：可在响应前后插入行为（改响应数据、注入 pslverr、
// 调整延迟），**无需改动 driver 本体**。
//
// 注册（test 的 build_phase）：
//   npu_sched_out_slave_driver_cb cb;
//   cb = npu_sched_out_slave_driver_cb::type_id::create("cb");
//   uvm_callbacks#(npu_sched_out_slave_driver,
//                  npu_sched_out_slave_driver_cb)::add(drv, cb);
//
// 注：typedef class 是前置声明 —— callback 方法签名要用到 driver 类型，
//     而 driver 定义在下方（SystemVerilog 要求先声明后使用）。

typedef class npu_sched_out_slave_driver;

class npu_sched_out_slave_driver_cb extends uvm_callback;
  `uvm_object_utils(npu_sched_out_slave_driver_cb)

  function new(string name = "npu_sched_out_slave_driver_cb");
    super.new(name);
  endfunction

  // 响应前：可修改 rsp 字段（响应数据、错误位、延迟）
  virtual task pre_drive(npu_sched_out_slave_driver drv,
                         npu_sched_out_slave_seq_item rsp);
  endtask

  // 响应后：时序记录 / 协议检查
  virtual task post_drive(npu_sched_out_slave_driver drv,
                          npu_sched_out_slave_seq_item rsp);
  endtask
endclass : npu_sched_out_slave_driver_cb

// ============================================================
// Slave Driver: npu_sched_out_slave_driver
// ============================================================

class npu_sched_out_slave_driver extends uvm_driver #(npu_sched_out_slave_seq_item);
  `uvm_component_utils(npu_sched_out_slave_driver)
  // 建立 driver 类型 ↔ callback 类型的回调池（uvm_do_callbacks 依赖它）
  `uvm_register_cb(npu_sched_out_slave_driver, npu_sched_out_slave_driver_cb)

  virtual npu_sched_out_if vif;
  npu_sched_out_port_config cfg;
  // pragma custom field_decl begin
  // pragma custom field_decl end

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual npu_sched_out_if)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Virtual interface not set")
    if (!uvm_config_db#(npu_sched_out_port_config)::get(this, "", "cfg", cfg))
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
    wait (vif.rst_n == 1'b1);
    forever begin
      npu_sched_out_slave_seq_item rsp;
      seq_item_port.get_next_item(rsp);
      drive_response(rsp);
      seq_item_port.item_done();
    end
  endtask

  virtual task drive_response(npu_sched_out_slave_seq_item rsp);
    // 回调：响应前（可改 rsp）
    `uvm_do_callbacks(npu_sched_out_slave_driver, npu_sched_out_slave_driver_cb,
                      pre_drive(this, rsp))
    // pragma custom drive_logic begin
    // 响应延迟（由 slave sequence 决定）
    repeat (rsp.delay_cycles) @(vif.slave_cb);
    // 默认：将请求字段回填到 slave 驱动的 input 端口
    @(vif.slave_cb);
    vif.slave_cb.issue_valid_slv <= rsp.issue_valid;   // 驱动的是从端影子变量
    vif.slave_cb.issue_unit_slv <= rsp.issue_unit;   // 驱动的是从端影子变量
    vif.slave_cb.issue_decision_slv <= rsp.issue_decision;   // 驱动的是从端影子变量
    // pragma custom drive_logic end
    // 回调：响应后
    `uvm_do_callbacks(npu_sched_out_slave_driver, npu_sched_out_slave_driver_cb,
                      post_drive(this, rsp))
  endtask
endclass : npu_sched_out_slave_driver
