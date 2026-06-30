// ============================================================
// Driver Callback
// ============================================================
typedef class ALU_out_driver;
typedef class ALU_out_sequencer;
class ALU_out_driver_callback extends uvm_callback;
  `uvm_object_utils(ALU_out_driver_callback)

  function new(string name = "ALU_out_driver_callback");
    super.new(name);
  endfunction

  virtual function void on_pre_drive(
    ALU_out_driver driver,
    ALU_out_seq_item item
  );
  endfunction

  virtual function void on_post_drive(
    ALU_out_driver driver,
    ALU_out_seq_item item
  );
  endfunction

  virtual function void on_item_received(
    ALU_out_driver driver,
    ALU_out_seq_item item
  );
  endfunction

  virtual function void on_item_done(
    ALU_out_driver driver,
    ALU_out_seq_item item
  );
  endfunction

  virtual function void on_reset(
    ALU_out_driver driver
  );
  endfunction

  virtual function void on_idle(
    ALU_out_driver driver
  );
  endfunction

endclass : ALU_out_driver_callback

// ============================================================
// Driver: ALU_out_driver
// Loopback-safe: expected written INSIDE drive_transaction
// to avoid race with monitor sampling at the next clock edge.
// ============================================================

class ALU_out_driver extends uvm_driver #(ALU_out_seq_item);
  `uvm_component_utils(ALU_out_driver)
  `uvm_register_cb(ALU_out_driver, ALU_out_driver_callback)

  virtual ALU_out_interface vif;
  ALU_out_config cfg;

  // Loopback self-test port: Driver expected -> Scoreboard
  uvm_analysis_port #(ALU_out_seq_item) expected_port;

  // --- Statistics ---
  protected int m_driven = 0;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    expected_port = new("expected_port", this);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(ALU_out_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("CFG", "Config not set")
    if (!uvm_config_db #(virtual ALU_out_interface)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Virtual interface not set")
  endfunction

  // --- Reset ---
  virtual task reset_signals();
    vif.cb.ready <= 0;
  endtask

  // --- Main drive ---
  // Reset handled inline (reset_phase not auto-scheduled without objection)
  task run_phase(uvm_phase phase);
    reset_signals();
    @(posedge vif.rst);
    get_and_drive();
  endtask

  // --- Receive and drive ---
  virtual task get_and_drive();
    ALU_out_seq_item req;
    forever begin
      seq_item_port.get_next_item(req);

      `uvm_do_callbacks(ALU_out_driver, ALU_out_driver_callback,
                        on_pre_drive(this, req))

      apply_drive_delay();

      drive_transaction(req);

      `uvm_do_callbacks(ALU_out_driver, ALU_out_driver_callback,
                        on_post_drive(this, req))

      seq_item_port.item_done();
    end
  endtask

  // --- Configurable delay ---
  virtual task apply_drive_delay();
    if (cfg.drive_delay_max > 0) begin
      int delay = $urandom_range(cfg.drive_delay_min, cfg.drive_delay_max);
      repeat(delay) @(vif.cb);
    end
  endtask

  // Drive transaction AND write expected to scoreboard INSIDE
  // to ensure expected arrives before monitor's next sample.
  // (custom_drive_logic placeholder filled by LLM with protocol timing)
  virtual task drive_transaction(ALU_out_seq_item req);
    // Copy expected values from item BEFORE driving
    ALU_out_seq_item exp = ALU_out_seq_item::type_id::create("exp");
    exp.result = req.result;
    exp.flags = req.flags;
    exp.valid = req.valid;


    // === Default: simple @(cb) drive all output ports (blocking on wire, no NBA delay) ===
    @(vif.cb);
    req.begin_time = $realtime;


    // Write expected NOW (before next @(vif.cb) where monitor samples)
    expected_port.write(exp);
    m_driven++;

    // Debug: print driven transaction
    `uvm_info("DRV", $sformatf("DRV: %s driven item #%0d:\n%s", get_name(), m_driven, req.sprint()), UVM_MEDIUM)
    // One cycle later: de-assert strobes
    @(vif.cb);
    vif.cb.ready <= 1'b0;
  endtask

  virtual function void report_phase(uvm_phase phase);
    `uvm_info("DRV", $sformatf(
      "Driver %s: driven=%0d", get_full_name(), m_driven), UVM_NONE)
  endfunction

endclass : ALU_out_driver
