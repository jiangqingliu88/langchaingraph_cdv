// Callback Example: ALU_in_callback_example
class ALU_in_callback_example extends ALU_in_callback_base;
  `uvm_object_utils(ALU_in_callback_example)

  function new(string name = "ALU_in_callback_example");
    super.new(name);
  endfunction

  // 示例：覆盖 Agent 连接回调
  virtual function void on_agent_connected(ALU_in_agent agent);
    `uvm_info(get_name(), $sformatf("ALU_in connected: %s", agent.get_full_name()), UVM_LOW)
  endfunction
endclass : ALU_in_callback_example
