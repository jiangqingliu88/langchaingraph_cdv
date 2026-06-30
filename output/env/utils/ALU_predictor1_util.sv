// ============================================================
// Predictor: 
// 自动生成 - 通过 YAML 配置端口
// ============================================================

class  extends uvm_component;
  `uvm_component_utils()
  // ─── 输入端口: ALU_in_agent_ae ───
  uvm_analysis_imp_ALU_in_agent_ae #(ALU_in_transaction, ) ALU_in_agent_ae;
  // ─── 输出端口: ALU_sb_ap ───
  uvm_analysis_port #(ALU_out_transaction) ALU_sb_ap;

  // ─── 内部统计 ───
  protected int ALU_in_agent_ae_count;
  protected ALU_in_transaction ALU_in_agent_ae_queue[$];
  protected int ALU_sb_ap_count;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    ALU_in_agent_ae = new("ALU_in_agent_ae", this);
    ALU_sb_ap = new("ALU_sb_ap", this);
  endfunction

  // ═══════════════════════════════════════════
  // TLM write
  // ═══════════════════════════════════════════
  virtual function void write_ALU_in_agent_ae(ALU_in_transaction tr);
    ALU_in_transaction clone;
    $cast(clone, tr.clone());
    ALU_in_agent_ae_queue.push_back(clone);
    ALU_in_agent_ae_count++;
    process_ALU_in_agent_ae(clone);
  endfunction

  // ═══════════════════════════════════════════
  // 处理逻辑（子类覆写）
  // ═══════════════════════════════════════════
  virtual function void process_ALU_in_agent_ae(ALU_in_transaction tr);
    // TODO: override in derived class
  endfunction

  // ═══════════════════════════════════════════
  // 输出
  // ═══════════════════════════════════════════
  virtual function void send_output(ALU_out_transaction tr);
    ALU_sb_ap.write(tr);
    ALU_sb_ap_count++;
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
    `uvm_info("PRED", $sformatf("  [IN]  ALU_in_agent_ae: %0d", ALU_in_agent_ae_count), UVM_NONE)
    `uvm_info("PRED", $sformatf("  [OUT] ALU_sb_ap: %0d", ALU_sb_ap_count), UVM_NONE)
    `uvm_info("PRED", "========================================", UVM_NONE)
  endfunction

endclass : 
```