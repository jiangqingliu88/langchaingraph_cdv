// Directed Test: alu_directed_test
// 执行特定场景测试

class alu_directed_test extends alu_base_test;
  `uvm_component_utils(alu_directed_test)

  function new(string name = "alu_directed_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // 定向测试配置
    cfg.ALU_in_cfg.is_active = UVM_ACTIVE;
    cfg.ALU_in_cfg.has_coverage = 1'b0;
    cfg.ALU_out_cfg.is_active = UVM_ACTIVE;
    cfg.ALU_out_cfg.has_coverage = 1'b0;
  endfunction

  virtual task run_phase(uvm_phase phase);
    phase.raise_objection(this);

    // 在所有 Agent Sequencer 上启动定向序列
    begin
      ALU_in_directed_seq _seq;
      _seq = ALU_in_directed_seq::type_id::create("_seq");
      _seq.start(env.ALU_in_agent_h.sqr);
    end
    begin
      ALU_out_directed_seq _seq;
      _seq = ALU_out_directed_seq::type_id::create("_seq");
      _seq.start(env.ALU_out_agent_h.sqr);
    end

    phase.drop_objection(this);
  endtask

endclass : alu_directed_test
