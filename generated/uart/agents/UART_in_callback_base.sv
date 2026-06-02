// Callback Base: UART_in_callback_base
class UART_in_callback_base extends UART_in_agent_callback;
  `uvm_object_utils(UART_in_callback_base)

  function new(string name = "UART_in_callback_base");
    super.new(name);
  endfunction

  // 用户可以在此覆盖基础回调方法
endclass : UART_in_callback_base
