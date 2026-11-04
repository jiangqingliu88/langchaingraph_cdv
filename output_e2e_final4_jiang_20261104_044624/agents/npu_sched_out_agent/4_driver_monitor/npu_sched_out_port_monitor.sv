// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════





// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright (c) 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     npu_sched_out_port_monitor.sv
//   作者:     -

//   联系邮箱: -
//   联系邮箱: -
//   描述:     tool_uvm 自动生成
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Port Monitor Callback: npu_sched_out_port_monitor_cb
// ============================================================
// UVM callback 扩展点：可在采样前后插入行为（改采样值、丢包、协议检查、
// 覆盖率打点），**无需改动 monitor 本体**。
//
// 注册（test 的 build_phase）：
//   npu_sched_out_port_monitor_cb cb;
//   cb = npu_sched_out_port_monitor_cb::type_id::create("cb");
//   uvm_callbacks#(npu_sched_out_port_monitor,
//                  npu_sched_out_port_monitor_cb)::add(mon, cb);
//
// master / slave 侧各有一对钩子：monitor 按 cfg.port_kind 只会走其中一条路径，
// 但两对都提供，便于同一个 cb 类同时服务两种实例。
//
// 注：typedef class 是前置声明 —— callback 方法签名要用到 monitor 类型，
//     而 monitor 定义在下方（SystemVerilog 要求先声明后使用）。

typedef class npu_sched_out_port_monitor;

class npu_sched_out_port_monitor_cb extends uvm_callback;
  `uvm_object_utils(npu_sched_out_port_monitor_cb)

  function new(string name = "npu_sched_out_port_monitor_cb");
    super.new(name);
  endfunction

  // ── master 侧（collect_transaction）──
  // 采样后：可修改 tx 字段（如归一化、屏蔽某位）
  virtual task post_sample(npu_sched_out_port_monitor mon,
                           npu_sched_out_master_seq_item tx);
  endtask

  // ── slave 侧（collect_slave_transaction）──
  virtual task post_sample_slave(npu_sched_out_port_monitor mon,
                                 npu_sched_out_slave_seq_item tx);
  endtask
endclass : npu_sched_out_port_monitor_cb

// ============================================================
// Port Monitor: npu_sched_out_port_monitor
// ============================================================
// 单类 monitor（不区分 master/slave）：按 cfg.port_kind 分支
//   master 侧 → master_mon_ap 抓 master_seq_item（expected/参考模型流）
//   slave 侧 → slave_mon_ap 抓 slave_seq_item（actual/比对流），
//     ACTIVE 时同时 clone 写入 slave sequencer 的 req_fifo（事件驱动响应）

class npu_sched_out_port_monitor extends uvm_monitor;
  `uvm_component_utils(npu_sched_out_port_monitor)
  // 建立 monitor 类型 ↔ callback 类型的回调池（uvm_do_callbacks 依赖它）
  `uvm_register_cb(npu_sched_out_port_monitor, npu_sched_out_port_monitor_cb)

  virtual npu_sched_out_if vif;
  npu_sched_out_port_config cfg;
  uvm_analysis_port #(npu_sched_out_master_seq_item) master_mon_ap;       // master 侧抓包
  uvm_analysis_port #(npu_sched_out_slave_seq_item) slave_mon_ap;  // slave 侧抓包
  npu_sched_out_slave_sequencer sqr;  // ★ slave 侧 Sequencer 句柄（ACTIVE 时连接）
  // pragma custom field_decl begin
  // pragma custom field_decl end

  function new(string name, uvm_component parent);
    super.new(name, parent);
    master_mon_ap = new("master_mon_ap", this);
    slave_mon_ap = new("slave_mon_ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual npu_sched_out_if)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Virtual interface not set")
    if (!uvm_config_db#(npu_sched_out_port_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Config not set")
    void'(uvm_config_db#(npu_sched_out_slave_sequencer)::get(this, "", "sqr", sqr));
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
    // monitor 的 forever 循环不 raise objection（避免悬挂）；复位门控后才开始采样
    wait (vif.rst_n == 1'b1);
    forever begin
      if (cfg.port_kind == MASTER) begin
        npu_sched_out_master_seq_item tx;
        tx = npu_sched_out_master_seq_item::type_id::create("tx");
        collect_transaction(tx);
        master_mon_ap.write(tx);
      end else begin
        npu_sched_out_slave_seq_item tx;
        tx = npu_sched_out_slave_seq_item::type_id::create("tx");
        collect_slave_transaction(tx);
        slave_mon_ap.write(tx);
        // ★ 核心：塞进 Sequencer FIFO
        if (sqr != null) begin
          npu_sched_out_slave_seq_item tx_clone;
          $cast(tx_clone, tx.clone());
          sqr.req_fifo.write(tx_clone);
        end
      end
    end
  endtask

  virtual task collect_transaction(npu_sched_out_master_seq_item tx);
    // pragma custom collect_logic begin
    @(vif.mon_cb);
    tx.issue_valid = vif.issue_valid;
    tx.issue_unit = vif.issue_unit;
    tx.issue_decision = vif.issue_decision;
    // pragma custom collect_logic end
    // 回调：master 侧采样后（可改 tx）
    `uvm_do_callbacks(npu_sched_out_port_monitor, npu_sched_out_port_monitor_cb,
                      post_sample(this, tx))
  endtask

  virtual task collect_slave_transaction(npu_sched_out_slave_seq_item tx);
    // pragma custom collect_slave_logic begin
    @(vif.mon_cb);
    tx.issue_valid = vif.issue_valid;
    tx.issue_unit = vif.issue_unit;
    tx.issue_decision = vif.issue_decision;
    // pragma custom collect_slave_logic end
    // 回调：slave 侧采样后（可改 tx）
    `uvm_do_callbacks(npu_sched_out_port_monitor, npu_sched_out_port_monitor_cb,
                      post_sample_slave(this, tx))
  endtask
endclass : npu_sched_out_port_monitor
