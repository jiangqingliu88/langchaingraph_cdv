// Callback Base: AXI_in_callback_base
class AXI_in_callback_base extends AXI_in_agent_callback;
  `uvm_object_utils(AXI_in_callback_base)

  function new(string name = "AXI_in_callback_base");
    super.new(name);
  endfunction

  // 用户可以在此覆盖基础回调方法
endclass : AXI_in_callback_base
