// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_master_driver.sv
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
// Master Driver: APB_master_driver
// ============================================================

class APB_master_driver extends uvm_driver #(APB_master_seq_item);
  `uvm_component_utils(APB_master_driver)

  virtual APB_if vif;
  APB_master_config cfg;
  // pragma custom field_decl begin
  // pragma custom field_decl end

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual APB_if)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Virtual interface not set")
    if (!uvm_config_db#(APB_master_config)::get(this, "", "cfg", cfg))
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
    // driver 的 forever 循环不 raise objection（避免悬挂）；复位门控后才开始驱动
    wait (vif.presetn == 1'b1);
    forever begin
      APB_master_seq_item req;
      seq_item_port.get_next_item(req);
      drive_transaction(req);
      seq_item_port.item_done();
    end
  endtask

  virtual task drive_transaction(APB_master_seq_item req);
    // pragma custom drive_logic begin
    // === APB 两拍时序: setup（addr/sel/write/data）→ access（penable）→ 等 pready → 撤拍 ===
    @(vif.master_cb);
    vif.master_cb.psel    <= 1'b1;
    vif.master_cb.paddr   <= req.paddr;
    vif.master_cb.pwrite  <= req.pwrite;
    vif.master_cb.pwdata  <= req.pwdata;
    @(vif.master_cb);
    vif.master_cb.penable <= 1'b1;
    do @(vif.master_cb); while (vif.master_cb.pready !== 1'b1);
    vif.master_cb.penable <= 1'b0;
    vif.master_cb.psel    <= 1'b0;
    // pragma custom drive_logic end
  endtask
endclass : APB_master_driver
