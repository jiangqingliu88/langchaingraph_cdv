// Callback Example: UART_out_callback_example
class UART_out_callback_example extends UART_out_callback_base;
  `uvm_object_utils(UART_out_callback_example)

  function new(string name = "UART_out_callback_example");
    super.new(name);
  endfunction

  // 示例：覆盖 Agent 连接回调
  virtual function void on_agent_connected(UART_out_agent agent);
    `uvm_info(get_name(), $sformatf("UART_out connected: %s", agent.get_full_name()), UVM_LOW)
  endfunction
endclass : UART_out_callback_example
