// Environment: alu
// 时钟/复位由 bench_top 统一管理

class alu extends uvm_env;
  `uvm_component_utils(alu)

  // 配置对象
  alu_config cfg;

  // Agent 实例
  ALU_in_agent ALU_in_agent_h;
  ALU_out_agent ALU_out_agent_h;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);

    if (!uvm_config_db #(alu_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Environment configuration not set")

    // 创建 Agent 并设置配置
    ALU_in_agent_h = ALU_in_agent::type_id::create("ALU_in_agent_h", this);
    uvm_config_db #(ALU_in_config)::set(this, "ALU_in_agent_h", "cfg", cfg.ALU_in_cfg);
    ALU_out_agent_h = ALU_out_agent::type_id::create("ALU_out_agent_h", this);
    uvm_config_db #(ALU_out_config)::set(this, "ALU_out_agent_h", "cfg", cfg.ALU_out_cfg);
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
  endfunction

  virtual function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    `uvm_info("ENV", "alu elaborated", UVM_LOW)
  endfunction

  function void report_phase(uvm_phase phase);
    uvm_report_server server;
    super.report_phase(phase);
    server = uvm_report_server::get_server();
    if (server.get_severity_count(UVM_ERROR) > 0 || server.get_severity_count(UVM_FATAL) > 0)
      `uvm_info("ENV", "*** TEST FAILED ***", UVM_NONE)
    else
      `uvm_info("ENV", "*** TEST PASSED ***", UVM_NONE)
  endfunction

endclass : alu
