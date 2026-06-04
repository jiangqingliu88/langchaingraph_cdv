// Callback Base: UART_out_callback_base
class UART_out_callback_base extends UART_out_agent_callback;
  `uvm_object_utils(UART_out_callback_base)

  function new(string name = "UART_out_callback_base");
    super.new(name);
  endfunction

  // 用户可以在此覆盖基础回调方法
endclass : UART_out_callback_base
