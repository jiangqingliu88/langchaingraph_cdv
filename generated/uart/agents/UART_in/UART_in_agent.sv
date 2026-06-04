// Agent: UART_in_agent

typedef class UART_in_agent;
typedef class UART_in_config;

class UART_in_agent extends uvm_agent;
  `uvm_component_utils(UART_in_agent)

  UART_in_sequencer  sqr;
  UART_in_driver      drv;
  UART_in_monitor     mon;
  UART_in_config      cfg;

  uvm_analysis_port #(UART_in_seq_item) agent_ap;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(UART_in_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Config not set")

    uvm_config_db #(UART_in_config)::set(this, "*", "cfg", cfg);

    mon = UART_in_monitor::type_id::create("mon", this);

    if (cfg.is_active == UVM_ACTIVE) begin
      sqr = UART_in_sequencer::type_id::create("sqr", this);
      drv = UART_in_driver::type_id::create("drv", this);
    end

    agent_ap = new("agent_ap", this);
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (cfg.is_active == UVM_ACTIVE)
      drv.seq_item_port.connect(sqr.seq_item_export);
    mon.item_collected_port.connect(agent_ap);
  endfunction

endclass : UART_in_agent
