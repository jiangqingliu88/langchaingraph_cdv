// Environment Configuration: apb_uart_env_config
// 自动生成，不要手动修改

class apb_uart_env_config extends uvm_object;
  `uvm_object_utils(apb_uart_env_config)

  // Agent 配置数组
  apb_uart_in_config apb_uart_in_cfg;
  apb_uart_out_config apb_uart_out_cfg;

  function new(string name = "apb_uart_env_config");
    super.new(name);
    apb_uart_in_cfg = apb_uart_in_config::type_id::create("apb_uart_in_cfg");
    apb_uart_out_cfg = apb_uart_out_config::type_id::create("apb_uart_out_cfg");
  endfunction

  // 配置有效性检查
  virtual function void check_config();
    // TODO: 实现配置合法性检查
  endfunction

endclass : apb_uart_env_config