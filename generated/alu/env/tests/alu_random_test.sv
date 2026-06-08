// Random Test: alu_random_test
// 随机事务 + 覆盖率收集

class alu_random_test extends alu_base_test;
  `uvm_component_utils(alu_random_test)

  rand int num_transactions = 100;

  function new(string name = "alu_random_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // 随机测试配置
    cfg.ALU_in_cfg.is_active = UVM_ACTIVE;
    cfg.ALU_in_cfg.has_coverage = 1'b1;
    cfg.ALU_out_cfg.is_active = UVM_ACTIVE;
    cfg.ALU_out_cfg.has_coverage = 1'b1;
  endfunction

  virtual task run_phase(uvm_phase phase);
    phase.raise_objection(this);

    // 在所有 Agent Sequencer 上启动随机序列
    begin
      ALU_in_random_seq _seq;
      _seq = ALU_in_random_seq::type_id::create("_seq");
      _seq.num_transactions = num_transactions;
      _seq.start(env.ALU_in_agent_h.sqr);
    end
    begin
      ALU_out_random_seq _seq;
      _seq = ALU_out_random_seq::type_id::create("_seq");
      _seq.num_transactions = num_transactions;
      _seq.start(env.ALU_out_agent_h.sqr);
    end

    phase.drop_objection(this);
  endtask

endclass : alu_random_test
