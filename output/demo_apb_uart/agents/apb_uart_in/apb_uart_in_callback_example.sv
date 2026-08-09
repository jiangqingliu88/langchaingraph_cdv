// Callback Example: apb_uart_in_callback_example
class apb_uart_in_callback_example extends apb_uart_in_callback_base;
  `uvm_object_utils(apb_uart_in_callback_example)

  function new(string name = "apb_uart_in_callback_example");
    super.new(name);
  endfunction

  // 示例：覆盖 Agent 连接回调
  virtual function void on_agent_connected(apb_uart_in_agent agent);
    `uvm_info(get_name(), $sformatf("apb_uart_in connected: %s", agent.get_full_name()), UVM_LOW)
  endfunction
endclass : apb_uart_in_callback_example
