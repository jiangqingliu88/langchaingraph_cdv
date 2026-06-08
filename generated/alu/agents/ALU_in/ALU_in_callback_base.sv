// Callback Base: ALU_in_callback_base
class ALU_in_callback_base extends ALU_in_agent_callback;
  `uvm_object_utils(ALU_in_callback_base)

  function new(string name = "ALU_in_callback_base");
    super.new(name);
  endfunction

  // 用户可以在此覆盖基础回调方法
endclass : ALU_in_callback_base
