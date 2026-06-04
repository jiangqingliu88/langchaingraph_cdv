// Agent: AXI_in_agent

typedef class AXI_in_agent;
typedef class AXI_in_config;

class AXI_in_agent extends uvm_agent;
  `uvm_component_utils(AXI_in_agent)

  AXI_in_sequencer  sqr;
  AXI_in_driver      drv;
  AXI_in_monitor     mon;
  AXI_in_config      cfg;

  uvm_analysis_port #(AXI_in_seq_item) agent_ap;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(AXI_in_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Config not set")

    uvm_config_db #(AXI_in_config)::set(this, "*", "cfg", cfg);

    mon = AXI_in_monitor::type_id::create("mon", this);

    if (cfg.is_active == UVM_ACTIVE) begin
      sqr = AXI_in_sequencer::type_id::create("sqr", this);
      drv = AXI_in_driver::type_id::create("drv", this);
    end

    agent_ap = new("agent_ap", this);
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (cfg.is_active == UVM_ACTIVE)
      drv.seq_item_port.connect(sqr.seq_item_export);
    mon.item_collected_port.connect(agent_ap);
  endfunction

endclass : AXI_in_agent
