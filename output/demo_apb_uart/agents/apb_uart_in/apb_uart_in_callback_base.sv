// Callback Base: apb_uart_in_callback_base
class apb_uart_in_callback_base extends apb_uart_in_agent_callback;
  `uvm_object_utils(apb_uart_in_callback_base)

  function new(string name = "apb_uart_in_callback_base");
    super.new(name);
  endfunction

  // 用户可以在此覆盖基础回调方法
endclass : apb_uart_in_callback_base
