// Environment Configuration: uart_env_config
// 自动生成，不要手动修改

class uart_env_config extends uvm_object;
  `uvm_object_utils(uart_env_config)

  // Agent 配置数组
  UART_in_config UART_in_cfg;

  function new(string name = "uart_env_config");
    super.new(name);
    UART_in_cfg = UART_in_config::type_id::create("UART_in_cfg");
  endfunction

  // 配置有效性检查
  virtual function void check_config();
    // TODO: 实现配置合法性检查
  endfunction

endclass : uart_env_config