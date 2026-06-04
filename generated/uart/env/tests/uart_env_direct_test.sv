// Directed Test: uart_env_directed_test
// 执行特定场景测试

class uart_env_directed_test extends uart_env_base_test;
  `uvm_component_utils(uart_env_directed_test)

  function new(string name = "uart_env_directed_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // 定向测试配置
    cfg.AXI_in_cfg.is_active = UVM_ACTIVE;
    cfg.AXI_in_cfg.has_coverage = 1'b0;
    cfg.UART_in_cfg.is_active = UVM_ACTIVE;
    cfg.UART_in_cfg.has_coverage = 1'b0;
    cfg.UART_out_cfg.is_active = UVM_ACTIVE;
    cfg.UART_out_cfg.has_coverage = 1'b0;
  endfunction

  virtual task run_phase(uvm_phase phase);
    phase.raise_objection(this);

    // 在所有 Agent Sequencer 上启动定向序列
    begin
      AXI_in_directed_seq _seq;
      _seq = AXI_in_directed_seq::type_id::create("_seq");
      _seq.start(env.AXI_in_agent_h.sqr);
    end
    begin
      UART_in_directed_seq _seq;
      _seq = UART_in_directed_seq::type_id::create("_seq");
      _seq.start(env.UART_in_agent_h.sqr);
    end
    begin
      UART_out_directed_seq _seq;
      _seq = UART_out_directed_seq::type_id::create("_seq");
      _seq.start(env.UART_out_agent_h.sqr);
    end

    phase.drop_objection(this);
  endtask

endclass : uart_env_directed_test
