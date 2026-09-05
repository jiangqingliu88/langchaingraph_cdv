// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════



// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     APB_slave_driver.sv
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
// Slave Driver: APB_slave_driver
// ============================================================

class APB_slave_driver extends uvm_driver #(APB_slave_seq_item);
  `uvm_component_utils(APB_slave_driver)

  virtual APB_if vif;
  APB_slave_config cfg;
  // pragma custom field_decl begin
  // pragma custom field_decl end

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual APB_if)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Virtual interface not set")
    if (!uvm_config_db#(APB_slave_config)::get(this, "", "cfg", cfg))
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
      APB_slave_seq_item rsp;
      seq_item_port.get_next_item(rsp);
      drive_response(rsp);
      seq_item_port.item_done();
    end
  endtask

  virtual task drive_response(APB_slave_seq_item rsp);
    // pragma custom drive_logic begin
    // === APB slave 响应: 等 setup+access 拍 → pready + 数据/错误 ===
    do @(vif.slave_cb); while (!(vif.slave_cb.psel && vif.slave_cb.penable));
    if (cfg.response_mode == AUTO_MEMORY) begin
      if (vif.slave_cb.pwrite)
        cfg.memory[vif.slave_cb.paddr] = vif.slave_cb.pwdata;
      else
        vif.slave_cb.prdata <= (cfg.memory.exists(vif.slave_cb.paddr))
                               ? cfg.memory[vif.slave_cb.paddr] : cfg.default_read_data;
    end else begin
      vif.slave_cb.prdata  <= rsp.prdata;
      vif.slave_cb.pslverr <= rsp.pslverr;
    end
    vif.slave_cb.pready <= 1'b1;
    @(vif.slave_cb);
    vif.slave_cb.pready <= 1'b0;
    // pragma custom drive_logic end
  endtask
endclass : APB_slave_driver
