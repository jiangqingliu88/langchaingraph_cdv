// Base Test: alu_base_test
// 所有具体 Test 的基类

class alu_base_test extends uvm_test;
  `uvm_component_utils(alu_base_test)

  // 环境实例
  alu env;

  // 环境配置
  alu_config cfg;
 
  // 虚拟接口
  virtual alu_in_interface ALU_in_vif;
  virtual alu_out_interface ALU_out_vif;

  function new(string name = "alu_base_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);

    // 创建并配置环境
    env = alu::type_id::create("env", this);
    
    // 创建并随机化配置
    cfg = alu_config::type_id::create("cfg");
    if (!cfg.randomize()) begin
      `uvm_fatal("CFG_RAND", "Failed to randomize environment configuration")
    end
    
    // 配置 Agent 模式
    cfg.ALU_in_cfg.is_active = UVM_ACTIVE;
    cfg.ALU_out_cfg.is_active = UVM_ACTIVE;

    // 设置配置到 config_db
    uvm_config_db #(alu_config)::set(this, "env", "cfg", cfg);
    
  endfunction

  virtual function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    `uvm_info("TEST", "alu_base_test elaborated", UVM_LOW)
  endfunction

  task run_phase(uvm_phase phase);
    ALU_in_random_seq ALU_in_seq;
    ALU_out_random_seq ALU_out_seq;
    phase.raise_objection(this);
    ALU_in_seq = ALU_in_random_seq::type_id::create("ALU_in_seq");
    ALU_in_seq.start(env.ALU_in_agent_h.sqr);
    ALU_out_seq = ALU_out_random_seq::type_id::create("ALU_out_seq");
    ALU_out_seq.start(env.ALU_out_agent_h.sqr);
    #1us;
    phase.drop_objection(this);
  endtask

endclass : alu_base_test