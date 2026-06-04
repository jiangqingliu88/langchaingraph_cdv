// Callback Example: AXI_in_callback_example
class AXI_in_callback_example extends AXI_in_callback_base;
  `uvm_object_utils(AXI_in_callback_example)

  function new(string name = "AXI_in_callback_example");
    super.new(name);
  endfunction

  // 示例：覆盖 Agent 连接回调
  virtual function void on_agent_connected(AXI_in_agent agent);
    `uvm_info(get_name(), $sformatf("AXI_in connected: %s", agent.get_full_name()), UVM_LOW)
  endfunction
endclass : AXI_in_callback_example
