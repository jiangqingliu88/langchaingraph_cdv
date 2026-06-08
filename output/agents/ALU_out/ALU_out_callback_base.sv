// Callback Base: ALU_out_callback_base
class ALU_out_callback_base extends ALU_out_agent_callback;
  `uvm_object_utils(ALU_out_callback_base)

  function new(string name = "ALU_out_callback_base");
    super.new(name);
  endfunction

  // 用户可以在此覆盖基础回调方法
endclass : ALU_out_callback_base
