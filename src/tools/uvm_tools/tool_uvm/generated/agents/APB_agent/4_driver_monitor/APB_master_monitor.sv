// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_master_monitor.sv
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
// Master Monitor: APB_master_monitor
// ============================================================

class APB_master_monitor extends uvm_monitor;
  `uvm_component_utils(APB_master_monitor)

  virtual APB_if vif;
  APB_master_config cfg;
  uvm_analysis_port #(APB_master_seq_item) mon_ap;
  // pragma custom field_decl begin
  // pragma custom field_decl end

  function new(string name, uvm_component parent);
    super.new(name, parent);
    mon_ap = new("mon_ap", this);
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
    // monitor 的 forever 循环不 raise objection（避免悬挂）；复位门控后才开始采样
    wait (vif.presetn == 1'b1);
    forever begin
      APB_master_seq_item tx;
      tx = APB_master_seq_item::type_id::create("tx");
      collect_transaction(tx);
      mon_ap.write(tx);
    end
  endtask

  virtual task collect_transaction(APB_master_seq_item tx);
    // pragma custom collect_logic begin
    // APB: 仅采样完整访问（penable && pready 拍）
    do @(vif.mon_cb); while (!(vif.mon_cb.psel && vif.mon_cb.penable && vif.mon_cb.pready));
    tx.paddr = vif.paddr;
    tx.pwrite = vif.pwrite;
    tx.pwdata = vif.pwdata;
    tx.prdata = vif.prdata;
    tx.pslverr = vif.pslverr;
    // pragma custom collect_logic end
  endtask
endclass : APB_master_monitor
