// Random Test: uart_env_random_test
// 执行随机测试

class uart_env_random_test extends uart_env_base_test;
  `uvm_component_utils(uart_env_random_test)

  function new(string name = "uart_env_random_test", uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // 随机测试特有配置
    cfg.randomize() with {
      UART_in_cfg.is_active == UVM_ACTIVE;
    };
  endfunction

  virtual task run_phase(uvm_phase phase);
    phase.raise_objection(this);

    // 在所有 Agent Sequencer 上启动随机序列
    begin
      UART_in_random_seq _seq;
      _seq = UART_in_random_seq::type_id::create("_seq");
      _seq.start(env.UART_in_agent_h.sqr);
    end

    phase.drop_objection(this);
  endtask

endclass : uart_env_random_test