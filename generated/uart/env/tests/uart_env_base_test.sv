// Base Test: uart_env_base_test
// 所有具体 Test 的基类

class uart_env_base_test extends uvm_test;
  `uvm_component_utils(uart_env_base_test)

  // 环境实例
  uart_env env;

  // 环境配置
  uart_env_config cfg;
 
  // 虚拟接口
  virtual axi4_lite_if_interface AXI_in_vif;
  virtual uart_if_interface UART_in_vif;
  virtual uart_if_interface UART_out_vif;

  function new(string name = "uart_env_base_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);

    // 创建并配置环境
    env = uart_env::type_id::create("env", this);
    
    // 创建并随机化配置
    cfg = uart_env_config::type_id::create("cfg");
    if (!cfg.randomize()) begin
      `uvm_fatal("CFG_RAND", "Failed to randomize environment configuration")
    end
    
    // 配置 Agent 模式
    cfg.AXI_in_cfg.is_active = UVM_ACTIVE;
    cfg.UART_in_cfg.is_active = UVM_ACTIVE;
    cfg.UART_out_cfg.is_active = UVM_ACTIVE;

    // 设置配置到 config_db
    uvm_config_db #(uart_env_config)::set(this, "env", "cfg", cfg);
    
    // 获取虚拟接口
    if (!uvm_config_db #(virtual axi4_lite_if_interface)::get(this, "", "AXI_in_vif", AXI_in_vif)) begin
      `uvm_fatal("VIF", $sformatf("Virtual interface not set for AXI_in"))
    end
    if (!uvm_config_db #(virtual uart_if_interface)::get(this, "", "UART_in_vif", UART_in_vif)) begin
      `uvm_fatal("VIF", $sformatf("Virtual interface not set for UART_in"))
    end
    if (!uvm_config_db #(virtual uart_if_interface)::get(this, "", "UART_out_vif", UART_out_vif)) begin
      `uvm_fatal("VIF", $sformatf("Virtual interface not set for UART_out"))
    end
    // 创建并注册错误注入 Callback
    /*
    *AXI_in_error_injection_callback err_cb;
    *err_cb = AXI_in_error_injection_callback::type_id::create("err_cb");
    *err_cb.error_rate = 20;
    *err_cb.inject_error = 1;
    *AXI_in_callback_base::add(
    *  env.AXI_in_agent_h.drv, err_cb
    *);
    *UART_in_error_injection_callback err_cb;
    *err_cb = UART_in_error_injection_callback::type_id::create("err_cb");
    *err_cb.error_rate = 20;
    *err_cb.inject_error = 1;
    *UART_in_callback_base::add(
    *  env.UART_in_agent_h.drv, err_cb
    *);
    *UART_out_error_injection_callback err_cb;
    *err_cb = UART_out_error_injection_callback::type_id::create("err_cb");
    *err_cb.error_rate = 20;
    *err_cb.inject_error = 1;
    *UART_out_callback_base::add(
    *  env.UART_out_agent_h.drv, err_cb
    *);
    */
  endfunction

  virtual function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    // 打印测试配置
    `uvm_info("TEST_CFG", $sformatf("Test: %s", get_name()), UVM_LOW)
    cfg.print();
  endfunction

  // 工厂覆盖方法（可在派生测试中重载）
  virtual function void set_factory_overrides();
    // TODO: 在此设置工厂覆盖
  endfunction

endclass : uart_env_base_test