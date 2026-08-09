// Base Test: apb_uart_env_base_test
// 所有具体 Test 的基类

class apb_uart_env_base_test extends uvm_test;
  `uvm_component_utils(apb_uart_env_base_test)

  // 环境实例
  apb_uart_env env;

  // 环境配置
  apb_uart_env_config cfg;
 
  // 虚拟接口
  virtual apb_uart_in_interface apb_uart_in_vif;
  virtual apb_uart_out_interface apb_uart_out_vif;

  function new(string name = "apb_uart_env_base_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);

    // 创建并配置环境
    env = apb_uart_env::type_id::create("env", this);
    
    // 创建并随机化配置
    cfg = apb_uart_env_config::type_id::create("cfg");
    if (!cfg.randomize()) begin
      `uvm_fatal("CFG_RAND", "Failed to randomize environment configuration")
    end
    
    // 配置 Agent 模式
    cfg.apb_uart_in_cfg.is_active = UVM_ACTIVE;
    cfg.apb_uart_out_cfg.is_active = UVM_ACTIVE;

    // 设置配置到 config_db
    uvm_config_db #(apb_uart_env_config)::set(this, "env", "cfg", cfg);
    
  endfunction

  virtual function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    `uvm_info("TEST", "apb_uart_env_base_test elaborated", UVM_LOW)
  endfunction

  task run_phase(uvm_phase phase);
    apb_uart_in_random_seq apb_uart_in_seq;
    apb_uart_out_random_seq apb_uart_out_seq;
    phase.raise_objection(this);
    apb_uart_in_seq = apb_uart_in_random_seq::type_id::create("apb_uart_in_seq");
    apb_uart_in_seq.start(env.apb_uart_in_agent_h.sqr);
    apb_uart_out_seq = apb_uart_out_random_seq::type_id::create("apb_uart_out_seq");
    apb_uart_out_seq.start(env.apb_uart_out_agent_h.sqr);
    #1us;
    phase.drop_objection(this);
  endtask

endclass : apb_uart_env_base_test