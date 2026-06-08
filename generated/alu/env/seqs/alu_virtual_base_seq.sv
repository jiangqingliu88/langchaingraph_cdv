// Virtual Base Sequence: alu_virtual_base_seq
// 增强版 - 支持仲裁、同步、超时控制

class alu_virtual_base_seq extends uvm_sequence;
  `uvm_object_utils(alu_virtual_base_seq)

  alu_config cfg;
  protected int m_started = 0;
  protected int m_completed = 0;

  function new(string name = "alu_virtual_base_seq");
    super.new(name);
  endfunction

  virtual task pre_body();
    if (!uvm_config_db #(alu_config)::get(get_sequencer(), "", "cfg", cfg))
      `uvm_fatal("VSEQ_CFG", "Config not set")
  endtask

  virtual task body();
    `uvm_info("VSEQ", "Virtual base seq body - override in derived", UVM_MEDIUM)
  endtask
  protected task start_ALU_in_sequence(uvm_sequence #(ALU_in_seq_item) _s);
    m_started++;
    fork
      _s.start(get_sequencer());
    join_none
  endtask

  protected task send_ALU_in_random(int count = 1);
    ALU_in_random_seq _rs;
    _rs = ALU_in_random_seq::type_id::create("_rs");
    _rs.num_transactions = count;
    start_ALU_in_sequence(_rs);
  endtask
  protected task start_ALU_out_sequence(uvm_sequence #(ALU_out_seq_item) _s);
    m_started++;
    fork
      _s.start(get_sequencer());
    join_none
  endtask

  protected task send_ALU_out_random(int count = 1);
    ALU_out_random_seq _rs;
    _rs = ALU_out_random_seq::type_id::create("_rs");
    _rs.num_transactions = count;
    start_ALU_out_sequence(_rs);
  endtask

endclass : alu_virtual_base_seq