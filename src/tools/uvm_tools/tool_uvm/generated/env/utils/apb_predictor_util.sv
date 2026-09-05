

// ════════════════════════════════════════════════════════════════
//   SignOffAI（功能签核） — 商标与权利声明
//   Copyright © 2026 SignOffAI（功能签核）. All rights reserved. 未经书面许可，禁止复制、修改、分发或用于商业用途。
// 
//   文件:     (unknown)
//   作者:     -
//   创建时间: 2026-09-05 19:56:58
//   修改时间: 2026-09-05 19:56:58
//   联系邮箱: -
//   描述:     APB 参考模型：预测 prdata/pslverr
// 
//   代码风格: 2 空格缩进 · 小写蛇形命名 · begin 同行 · 中文注释 ·
//             宏/参数全大写 · 禁 magic number —— 详见 prompt.md
// ════════════════════════════════════════════════════════════════


// ============================================================
// Predictor: apb_predictor
// 自动生成 - 通过 YAML 配置端口
// ============================================================

class apb_predictor extends uvm_component;
  `uvm_component_utils(apb_predictor)
  // ─── 输入端口: in_export ───
  uvm_analysis_imp_in_export #(APB_master_seq_item, apb_predictor) in_export;
  // ─── 输出端口: out_port ───
  uvm_analysis_port #(APB_master_seq_item) out_port;

  // ─── 内部统计 ───
  protected int in_export_count;
  protected APB_master_seq_item in_export_queue[$];
  protected int out_port_count;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    in_export = new("in_export", this);
    out_port = new("out_port", this);
  endfunction

  // ═══════════════════════════════════════════
  // TLM write
  // ═══════════════════════════════════════════
  virtual function void write_in_export(APB_master_seq_item tr);
    APB_master_seq_item clone;
    $cast(clone, tr.clone());
    in_export_queue.push_back(clone);
    in_export_count++;
    process_in_export(clone);
  endfunction

  // ═══════════════════════════════════════════
  // 处理逻辑（子类覆写）
  // ═══════════════════════════════════════════
  virtual function void process_in_export(APB_master_seq_item tr);
    // TODO: override in derived class
  endfunction

  // ═══════════════════════════════════════════
  // 输出
  // ═══════════════════════════════════════════
  virtual function void send_output(APB_master_seq_item tr);
    out_port.write(tr);
    out_port_count++;
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
    `uvm_info("PRED", $sformatf("  [IN]  in_export: %0d", in_export_count), UVM_NONE)
    `uvm_info("PRED", $sformatf("  [OUT] out_port: %0d", out_port_count), UVM_NONE)
    `uvm_info("PRED", "========================================", UVM_NONE)
  endfunction

endclass : apb_predictor
```