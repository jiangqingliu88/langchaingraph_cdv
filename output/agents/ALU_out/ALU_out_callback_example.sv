// Callback Example: ALU_out_callback_example
class ALU_out_callback_example extends ALU_out_callback_base;
  `uvm_object_utils(ALU_out_callback_example)

  function new(string name = "ALU_out_callback_example");
    super.new(name);
  endfunction

  // 示例：覆盖 Agent 连接回调
  virtual function void on_agent_connected(ALU_out_agent agent);
    `uvm_info(get_name(), $sformatf("ALU_out connected: %s", agent.get_full_name()), UVM_LOW)
  endfunction
endclass : ALU_out_callback_example
