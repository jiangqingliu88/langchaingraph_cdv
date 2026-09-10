

// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     (unknown)
//   作者:     -
//   创建时间: 2026-09-09 17:58:44
//   修改时间: 2026-09-09 17:58:44
//   联系邮箱: -
//   描述:     APB 监控汇聚点（多输入 → 单输出）
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Predictor: apb_monitor_sink
// 自动生成 - 通过 YAML 配置端口
// ============================================================

class apb_monitor_sink extends uvm_component;
  `uvm_component_utils(apb_monitor_sink)
  // ─── 输入端口: master_export ───
  uvm_analysis_imp_master_export #(apb_master_seq_item, apb_monitor_sink) master_export;
  // ─── 输入端口: slave_export ───
  uvm_analysis_imp_slave_export #(apb_slave_seq_item, apb_monitor_sink) slave_export;
  // ─── 输出端口: merged_out ───
  uvm_analysis_port #(apb_master_seq_item) merged_out;

  // ─── 内部统计 ───
  protected int master_export_count;
  protected apb_master_seq_item master_export_queue[$];
  protected int slave_export_count;
  protected apb_slave_seq_item slave_export_queue[$];
  protected int merged_out_count;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    master_export = new("master_export", this);
    slave_export = new("slave_export", this);
    merged_out = new("merged_out", this);
  endfunction

  // ═══════════════════════════════════════════
  // TLM write
  // ═══════════════════════════════════════════
  virtual function void write_master_export(apb_master_seq_item tr);
    apb_master_seq_item clone;
    $cast(clone, tr.clone());
    master_export_queue.push_back(clone);
    master_export_count++;
    process_master_export(clone);
  endfunction
  virtual function void write_slave_export(apb_slave_seq_item tr);
    apb_slave_seq_item clone;
    $cast(clone, tr.clone());
    slave_export_queue.push_back(clone);
    slave_export_count++;
    process_slave_export(clone);
  endfunction

  // ═══════════════════════════════════════════
  // 处理逻辑（子类覆写）
  // ═══════════════════════════════════════════
  virtual function void process_master_export(apb_master_seq_item tr);
    // TODO: override in derived class
  endfunction
  virtual function void process_slave_export(apb_slave_seq_item tr);
    // TODO: override in derived class
  endfunction

  // ═══════════════════════════════════════════
  // 输出
  // ═══════════════════════════════════════════
  virtual function void send_output(apb_master_seq_item tr);
    merged_out.write(tr);
    merged_out_count++;
  endfunction

  // ═══════════════════════════════════════════
  // 报告
  // ═══════════════════════════════════════════

  virtual function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    `uvm_info("PRED", "", UVM_NONE)
    `uvm_info("PRED", "========================================", UVM_NONE)
    `uvm_info("PRED", $sformatf("Predictor: %s", get_full_name()), UVM_NONE)
    `uvm_info("PRED", "========================================", UVM_NONE)
    `uvm_info("PRED", $sformatf("  [IN]  master_export: %0d", master_export_count), UVM_NONE)
    `uvm_info("PRED", $sformatf("  [IN]  slave_export: %0d", slave_export_count), UVM_NONE)
    `uvm_info("PRED", $sformatf("  [OUT] merged_out: %0d", merged_out_count), UVM_NONE)
    `uvm_info("PRED", "========================================", UVM_NONE)
  endfunction

endclass : apb_monitor_sink
```