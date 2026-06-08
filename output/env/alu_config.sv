// Environment Configuration: alu_config
// 自动生成，不要手动修改

class alu_config extends uvm_object;
  `uvm_object_utils(alu_config)
  rand bit has_scoreboard;
  rand bit has_functional_coverage;
  rand bit has_virtual_sequencer;
  rand int num_transactions;
  constraint env_config_valid_c { has_scoreboard == 1 -> has_functional_coverage == 1; }
  constraint transaction_limit_c { num_transactions inside {[1:1000]}; }

  // Agent 配置数组
  ALU_in_config ALU_in_cfg;
  ALU_out_config ALU_out_cfg;

  function new(string name = "alu_config");
    super.new(name);
    ALU_in_cfg = ALU_in_config::type_id::create("ALU_in_cfg");
    ALU_out_cfg = ALU_out_config::type_id::create("ALU_out_cfg");
  endfunction

  // 配置有效性检查
  virtual function void check_config();
    // TODO: 实现配置合法性检查
  endfunction

endclass : alu_config