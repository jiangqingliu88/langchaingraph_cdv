//-----------------------------------------------------------------------------
// npu_tb_player.svh
//
// Core coordinator: preflight (four read-only scans, then one declaration
// side effect), run, shutdown and trace.  See readme.md for the contract.
//
// The player only talks to:
//   · npu_player_clock / npu_player_event_bus / npu_player_memory_if (runtime)
//   · uvm_sequencer_base + uvm_object_wrapper (bound sequences)
//   · npu_player_trace_hook (optional subscriber facade)
// It never imports the env, an agent or a concrete memory model.
//-----------------------------------------------------------------------------
`ifndef NPU_TB_PLAYER_SVH
`define NPU_TB_PLAYER_SVH

class npu_tb_player extends uvm_component;
  `uvm_component_utils(npu_tb_player)

  // ── configuration / runtime ──────────────────────────────────────────────
  npu_player_cfg            cfg;
  npu_player_runtime        runtime;
  npu_player_trace_hook     trace_hook;

  // ── program and outcome ──────────────────────────────────────────────────
  npu_player_program        playback;
  npu_player_status         status;
  string                    error;
  int                       completed_actions;
  npu_player_observation    observations[$];

  // ── lifecycle flags (one-shot) ───────────────────────────────────────────
  bit                    bindings_sealed;
  bit                    preflight_complete;
  bit                    playback_attempted;
  bit                    playback_active;
  bit                    stop_requested;
  longint unsigned       consumer_reset_epoch;
  longint unsigned       command_clock_ticks;
  bit                    result_saved;
  int                    trace_fd;

  // ── bindings ─────────────────────────────────────────────────────────────
  string                 bound_ops[string];
  uvm_sequencer_base     seqr_by_op[string];
  uvm_object_wrapper     seq_type_by_op[string];
  npu_player_op_handler  handler_by_op[string];
  npu_player_op_validator validator_by_op[string];
  string                 shutdown_targets[$];
  bit                    stopped[string];
  bit                    drained[string];
  bit                    finished[string];

  // ── watchdog deadlines (action index -> absolute command tick) ───────────
  longint unsigned       watchdog_deadline_by_action[int];

  function new(string name = "npu_tb_player", uvm_component parent = null);
    super.new(name, parent);
    status = NP_SUCCESS;
    error = "";
    completed_actions = 0;
    bindings_sealed = 0;
    preflight_complete = 0;
    playback_attempted = 0;
    playback_active = 0;
    stop_requested = 0;
    consumer_reset_epoch = 0;
    command_clock_ticks = 0;
    result_saved = 0;
    trace_fd = 0;
  endfunction

  //===========================================================================
  // Assembly (env side)
  //===========================================================================
  virtual function void build_phase(uvm_phase phase);
    npu_player_cfg db_cfg;
    super.build_phase(phase);
    if (uvm_config_db#(npu_player_cfg)::get(this, "", "cfg", db_cfg))
      cfg = db_cfg;
    if (!uvm_config_db#(npu_player_runtime)::get(this, "", "runtime", runtime))
      runtime = new();
    if (cfg == null) begin
      if (runtime.cfg != null) cfg = runtime.cfg;
      else cfg = new();
    end
    if (runtime.cfg == null) runtime.cfg = cfg;
    runtime.ensure_defaults();
    if (!uvm_config_db#(npu_player_trace_hook)::get(this, "", "trace_hook", trace_hook))
      trace_hook = null;
    $timeformat(-15, 0, " fs", 1);
    if (cfg.trace_file != "-" && cfg.trace_file != "")
      open_trace();
  endfunction

  function void set_runtime(npu_player_runtime value);
    runtime = value;
    if (runtime == null) return;
    if (runtime.cfg == null) runtime.cfg = cfg;
    runtime.ensure_defaults();
  endfunction

  function void set_trace_hook(npu_player_trace_hook value);
    trace_hook = value;
  endfunction

  function void connect_memory(npu_player_memory_if value);
    if (bindings_sealed || playback_attempted) begin
      `uvm_error("NPU_PLAYER", "connect_memory() rejected: bindings already sealed")
      return;
    end
    runtime.memory = value;
  endfunction

  function void bind_sequence(string op, uvm_sequencer_base sequencer,
                              uvm_object_wrapper sequence_type);
    if (bindings_sealed || playback_attempted) begin
      `uvm_error("NPU_PLAYER", $sformatf("bind_sequence(%s) rejected: bindings already sealed", op))
      return;
    end
    op = npu_player_program::normalize_op(op);
    bound_ops[op] = op;
    seqr_by_op[op] = sequencer;
    seq_type_by_op[op] = sequence_type;
  endfunction

  function void bind_handler(string op, npu_player_op_handler handler);
    if (bindings_sealed || playback_attempted) begin
      `uvm_error("NPU_PLAYER", $sformatf("bind_handler(%s) rejected: bindings already sealed", op))
      return;
    end
    op = npu_player_program::normalize_op(op);
    bound_ops[op] = op;
    handler_by_op[op] = handler;
    validator_by_op[op] = handler;
  endfunction

  function void bind_validator(string op, npu_player_op_validator validator);
    op = npu_player_program::normalize_op(op);
    validator_by_op[op] = validator;
  endfunction

  function void add_shutdown_target(string name);
    shutdown_targets.push_back(name);
  endfunction

  //===========================================================================
  // Preflight - four scans; nothing external is touched before scan 4.
  //===========================================================================
  function bit preflight(output string err);
    if (playback_attempted || playback_active) begin
      err = "preflight() after play()";
      return 0;
    end
    if (bindings_sealed || preflight_complete) begin
      err = "preflight() called twice";
      return 0;
    end
    status = NP_SUCCESS;
    error = "";
    playback = new();
    if (!playback.scan(cfg.commands_file, cfg.max_file_bytes, cfg.max_actions, err)) begin
      status = NP_INPUT_ERROR;
      return 0;
    end
    if (!playback.attach_metadata(cfg.metadata_file, cfg.max_file_bytes, err)) begin
      status = NP_INPUT_ERROR;
      return 0;
    end
    if (!static_scan(err)) begin
      status = NP_INPUT_ERROR;
      return 0;
    end
    if (!validate_external_ops(err)) begin
      status = NP_INPUT_ERROR;
      return 0;
    end
    declare_local_producers();
    preflight_complete = 1;
    bindings_sealed = 1;
    err = "";
    return 1;
  endfunction

  protected function bit static_scan(output string err);
    bit [15:0]       dispatch_mask = 16'hffff;
    int              batch_depth = 0;
    int unsigned     local_signals[string];
    int unsigned     waits[string];
    string           event_names[string];
    npu_player_action action;

    foreach (playback.actions[i]) begin
      action = playback.actions[i];

      // scan 1: normalize the raw container.
      if (!normalize_raw(action, err)) return 0;

      // scan 2: structural checks, still side-effect free.
      case (action.kind)
        NP_ACT_MEM_INIT, NP_ACT_MEM_SCRUB: begin
          if (runtime.memory == null) begin
            err = $sformatf("action %0d %s: no memory backend", action.index, action.op);
            return 0;
          end
          if (action.kind == NP_ACT_MEM_INIT) begin
            npu_player_mem_init request = new();
            if (!request.from_action(action, playback.base_dir, err)) return 0;
          end
          else begin
            npu_player_mem_scrub request = new();
            if (!request.from_action(action, err)) return 0;
          end
        end
        NP_ACT_DISPATCH_MASK: begin
          longint unsigned mask;
          if (!action.get_uint("mask", mask) || mask > 16'hffff) begin
            err = $sformatf("action %0d dispatch_mask needs a 16-bit mask", action.index);
            return 0;
          end
          dispatch_mask = mask[15:0];
        end
        NP_ACT_DISPATCH_SKIP: begin
          longint unsigned core_value, target_value;
          if (!action.get_uint("core_id", core_value) || int'(core_value) != cfg.core_id) begin
            err = $sformatf("action %0d dispatch_skip belongs to another core", action.index);
            return 0;
          end
          if (!action.get_uint("target_mask", target_value)) begin
            err = $sformatf("action %0d dispatch_skip has no target_mask", action.index);
            return 0;
          end
          if (target_value[cfg.core_id]) begin
            err = $sformatf("action %0d dispatch_skip targets this core", action.index);
            return 0;
          end
          action.skipped = 1;
        end
        NP_ACT_HARDWARE: begin
          if (!action.has_cmddata) begin
            err = $sformatf("action %0d %s: missing cmddata (attach commands.json)",
                            action.index, action.op);
            return 0;
          end
          if (!bound_ops.exists(action.op)) begin
            err = $sformatf("action %0d %s: no sequence/handler binding",
                            action.index, action.op);
            return 0;
          end
        end
        default: begin
          // built-in controls are checked below; direct extensions here
        end
      endcase

      if (action.kind == NP_ACT_CONTROL) begin
        if (!npu_player_program::is_builtin_control(action.op)) begin
          string direct_error;
          if (!bound_ops.exists(action.op) && !validates_direct(action, direct_error)) begin
            err = $sformatf("action %0d %s: %s", action.index, action.op,
                            direct_error == "" ? "unsupported control op" : direct_error);
            return 0;
          end
        end
        else if (action.op == "batch_begin") batch_depth++;
        else if (action.op == "batch_end") begin
          if (batch_depth == 0) begin
            err = $sformatf("action %0d: batch_end without batch_begin", action.index);
            return 0;
          end
          batch_depth--;
        end
        else if (action.op == "signal_event") begin
          string event_name = event_of(action);
          if (event_name == "") begin
            err = $sformatf("action %0d signal_event needs an event", action.index);
            return 0;
          end
          event_names[event_name] = event_name;
          local_signals[event_name] = (local_signals.exists(event_name) ? local_signals[event_name] : 0) + 1;
        end
        else if (action.op == "wait_event" || action.op == "wait_done") begin
          string event_name = event_of(action);
          if (event_name == "") begin
            err = $sformatf("action %0d %s needs an event/tag", action.index, action.op);
            return 0;
          end
          event_names[event_name] = event_name;
          waits[event_name] = (waits.exists(event_name) ? waits[event_name] : 0) + 1;
          if (!runtime.events.has_external_producer(event_name) &&
              local_signals[event_name] < waits[event_name]) begin
            err = $sformatf("action %0d %s: event '%s' has no local signal and no external producer",
                            action.index, action.op, event_name);
            return 0;
          end
        end
        else if (action.op == "wait_cycles") begin
          longint unsigned cycles;
          if (!action.get_uint("n", cycles) && !action.get_uint("cycles", cycles)) begin
            err = $sformatf("action %0d wait_cycles needs n/cycles", action.index);
            return 0;
          end
        end
        else if (action.op == "watchdog") begin
          longint unsigned cycles;
          if (!action.get_uint("cycles", cycles) && !action.get_uint("timeout_cycles", cycles)) begin
            err = $sformatf("action %0d watchdog needs cycles/timeout_cycles", action.index);
            return 0;
          end
        end
      end
    end

    if (batch_depth != 0) begin
      err = "unbalanced batch_begin/batch_end";
      return 0;
    end
    if (event_names.size() > cfg.max_event_names) begin
      err = $sformatf("too many event names (max %0d)", cfg.max_event_names);
      return 0;
    end
    err = "";
    return 1;
  endfunction

  protected function bit normalize_raw(npu_player_action action, output string err);
    if (action.has_data75 && action.has_cmddata) begin
      err = $sformatf("action %0d has both cmddata and data75 containers", action.index);
      return 0;
    end
    if (action.has_data75) begin
      if (cfg.raw75_layout != "flag_msb") begin
        err = $sformatf("action %0d data75 requires cfg.raw75_layout=\"flag_msb\"", action.index);
        return 0;
      end
      action.cmddata = action.data75[73:0];
      action.instr_flag = action.data75[74];
      action.has_cmddata = 1;
    end
    err = "";
    return 1;
  endfunction

  protected function bit validate_external_ops(output string err);
    npu_player_action action;
    npu_player_op_validator validator;
    foreach (playback.actions[i]) begin
      action = playback.actions[i];
      if (action.skipped) continue;
      if (!validator_by_op.exists(action.op)) continue;
      validator = validator_by_op[action.op];
      if (validator != null && !validator.validate(action, err)) begin
        err = $sformatf("action %0d %s failed preflight validation: %s",
                        action.index, action.op, err);
        return 0;
      end
    end
    err = "";
    return 1;
  endfunction

  protected function void declare_local_producers();
    string event_name;
    foreach (playback.actions[i]) begin
      if (playback.actions[i].op != "signal_event") continue;
      event_name = event_of(playback.actions[i]);
      if (event_name != "")
        runtime.events.declare_local_producer(event_name);
    end
  endfunction

  protected function string event_of(npu_player_action action);
    string value;
    if (action.params == null) return "";
    if (action.params.get_string("event", value)) return value;
    if (action.params.get_string("tag", value)) return value;
    return "";
  endfunction

  // Extension point: a subclass claims an op that is neither built-in nor
  // memory-backed (for example peer_cfg).
  virtual function bit validates_direct(npu_player_action action, output string error);
    error = $sformatf("unsupported control op: %s", action.op);
    return 0;
  endfunction

  //===========================================================================
  // Playback
  //===========================================================================
  task play();
    if (playback_attempted || playback_active) begin
      `uvm_error("NPU_PLAYER", "play() is one-shot; create a new player for a new program")
      return;
    end
    if (!preflight_complete) begin
      `uvm_error("NPU_PLAYER", "play() called before a successful preflight()")
      status = NP_BLOCKED;
      return;
    end
    playback_attempted = 1;
    playback_active = 1;
    status = NP_SUCCESS;
    error = "";
    completed_actions = 0;
    stop_requested = 0;
    command_clock_ticks = 0;
    dispatch_watchdog_epoch_begin();
    trace_event("env.START",
                $sformatf("core=%0d actions=%0d", cfg.core_id, playback.actions.size()));
    fork
      run_actions();
      run_global_timeout();
      cycle_watchdogs();
    join_any
    disable fork;
    request_stop_once();
    finish_targets();
    playback_active = 0;
    trace_event("env.END",
                $sformatf("status=%s completed=%0d",
                          npu_player_status_name(status), completed_actions));
    save_result();
  endtask

  virtual task run_actions();
    npu_player_receipt ready;
    npu_player_receipt receipt;
    npu_player_action action;
    bit timed_out;

    runtime.clock_service.wait_ready(ready);
    if (ready == null || !ready.ok()) begin
      fail(ready == null ? NP_BLOCKED : ready.status,
           ready == null ? "clock wait_ready returned null" : ready.error);
      return;
    end
    consumer_reset_epoch = runtime.clock_service.epoch();
    if (runtime.events.epoch() != consumer_reset_epoch) begin
      fail(NP_BLOCKED, $sformatf("event epoch %0d != clock epoch %0d",
                                 runtime.events.epoch(), consumer_reset_epoch));
      return;
    end

    foreach (playback.actions[i]) begin
      if (stop_requested) break;
      if (runtime.clock_service.epoch() != runtime.events.epoch()) begin
        fail(NP_EXEC_ERROR, "reset epoch changed between actions");
        return;
      end
      action = playback.actions[i];
      trace_event("env.ACTION_START",
                  $sformatf("index=%0d op=%s line=%0d", action.index, action.op, action.line));
      timed_out = 0;
      receipt = null;
      fork
        execute_one(action, receipt);
        begin
          #(cfg.action_timeout);
          timed_out = 1;
        end
      join_any
      disable fork;
      if (timed_out) begin
        fail(NP_TIMEOUT, $sformatf("action %0d %s exceeded action_timeout", action.index, action.op));
        return;
      end
      if (receipt == null) begin
        fail(NP_EXEC_ERROR, $sformatf("action %0d %s returned no receipt", action.index, action.op));
        return;
      end
      if (!receipt.ok()) begin
        fail(receipt.status, $sformatf("action %0d %s: %s", action.index, action.op,
                                       receipt.error == "" ? "receipt not SUCCESS" : receipt.error));
        return;
      end
      if (action.kind == NP_ACT_HARDWARE || action.kind == NP_ACT_MEM_INIT ||
          action.kind == NP_ACT_MEM_SCRUB) begin
        // Hardware receipts must be real advancement evidence.
        if (action.kind == NP_ACT_HARDWARE &&
            (receipt.phase != "cmd accept" || receipt.handle == "" ||
             receipt.epoch != consumer_reset_epoch)) begin
          fail(NP_EXEC_ERROR,
               $sformatf("action %0d %s: CMD executor must return actual cmd accept (phase=%s handle=%s epoch=%0d)",
                         action.index, action.op, receipt.phase, receipt.handle, receipt.epoch));
          return;
        end
      end
      begin
        npu_player_observation observation = new(action, receipt);
        observations.push_back(observation);
      end
      completed_actions++;
      trace_event("env.ACTION_END",
                  $sformatf("index=%0d phase=%s handle=%s",
                            action.index, receipt.phase, receipt.handle));
    end
  endtask

  protected task execute_one(npu_player_action action, output npu_player_receipt receipt);
    string direct_error;
    bit handled;
    execute_builtin(action, receipt, handled);
    if (handled) return;
    if (action.skipped) begin
      receipt = npu_player_receipt::success("dispatch_local", "", runtime.clock_service.epoch());
      return;
    end
    if (handler_by_op.exists(action.op)) begin
      handler_by_op[action.op].execute(action, receipt);
      return;
    end
    if (seq_type_by_op.exists(action.op)) begin
      execute_sequence(action, receipt);
      return;
    end
    if (action.kind == NP_ACT_MEM_INIT || action.kind == NP_ACT_MEM_SCRUB ||
        validates_direct(action, direct_error)) begin
      execute_direct(action, receipt);
      return;
    end
    receipt = npu_player_receipt::failure(NP_EXEC_ERROR,
        $sformatf("no executor for op %s", action.op));
  endtask

  protected task execute_builtin(npu_player_action action,
                                 output npu_player_receipt receipt,
                                 output bit handled);
    string event_name;
    npu_player_receipt clock_receipt;
    longint unsigned cycles;
    receipt = null;
    handled = 1;
    case (action.op)
      "wait_cycles": begin
        cycles = action.uint_or("n", action.uint_or("cycles", 0));
        runtime.clock_service.wait_cycles(cycles, clock_receipt);
        if (clock_receipt == null || !clock_receipt.ok()) begin
          receipt = clock_receipt;
          return;
        end
        receipt = npu_player_receipt::success("cycles", "", clock_receipt.epoch);
      end
      "nop": begin
        runtime.clock_service.wait_cycles(1, clock_receipt);
        if (clock_receipt == null || !clock_receipt.ok()) begin
          receipt = clock_receipt;
          return;
        end
        receipt = npu_player_receipt::success("cycles", "", clock_receipt.epoch);
      end
      "signal_event": begin
        string publish_error;
        event_name = event_of(action);
        if (!runtime.events.publish(event_name, publish_error)) begin
          receipt = npu_player_receipt::failure(NP_EXEC_ERROR, publish_error);
          return;
        end
        receipt = npu_player_receipt::success("event_published", event_name,
                                              runtime.clock_service.epoch());
      end
      "wait_event", "wait_done": begin
        event_name = event_of(action);
        wait_for_event(action, event_name, receipt);
      end
      "checkpoint": begin
        receipt = npu_player_receipt::success("group_marker", "", runtime.clock_service.epoch());
      end
      "watchdog": begin
        cycles = action.uint_or("cycles", action.uint_or("timeout_cycles", 0));
        watchdog_deadline_by_action[action.index] = command_clock_ticks + cycles;
        receipt = npu_player_receipt::success("watchdog_armed", "", runtime.clock_service.epoch());
      end
      "dispatch_mask": begin
        receipt = npu_player_receipt::success("dispatch_local", "", runtime.clock_service.epoch());
      end
      "dispatch_skip": begin
        receipt = npu_player_receipt::success("dispatch_local", "", runtime.clock_service.epoch());
      end
      "batch_begin", "batch_end": begin
        receipt = npu_player_receipt::success("group_marker", "", runtime.clock_service.epoch());
      end
      default: handled = 0;
    endcase
  endtask

  protected task wait_for_event(npu_player_action action, string event_name,
                                output npu_player_receipt receipt);
    int unsigned wanted;
    longint unsigned timeout;
    npu_player_receipt clock_receipt;
    wanted = int'(action.uint_or("count", 1));
    timeout = action.uint_or("timeout_cycles", cfg.default_event_timeout_cycles);
    for (longint unsigned i = 0; i < timeout; i++) begin
      if (runtime.events.count(event_name) >= wanted) begin
        receipt = npu_player_receipt::success("event_consumed", event_name,
                                              runtime.clock_service.epoch());
        return;
      end
      if (runtime.clock_service.epoch() != runtime.events.epoch()) begin
        receipt = npu_player_receipt::failure(NP_EXEC_ERROR,
            $sformatf("event epoch changed while waiting for %s", event_name));
        return;
      end
      runtime.clock_service.wait_cycles(1, clock_receipt);
      if (clock_receipt == null || !clock_receipt.ok()) begin
        receipt = clock_receipt;
        return;
      end
    end
    receipt = npu_player_receipt::failure(NP_TIMEOUT,
        $sformatf("wait for event '%s' timed out after %0d cycles", event_name, timeout));
  endtask

  protected task execute_sequence(npu_player_action action, output npu_player_receipt receipt);
    uvm_object_wrapper     wrapper = seq_type_by_op[action.op];
    uvm_sequencer_base     sequencer = seqr_by_op[action.op];
    uvm_object             object_value;
    uvm_sequence_base      seq_handle;
    npu_player_cmd_sequence cmd_sequence;
    if (wrapper == null || sequencer == null) begin
      receipt = npu_player_receipt::failure(NP_EXEC_ERROR,
          $sformatf("op %s has an incomplete sequence binding", action.op));
      return;
    end
    object_value = wrapper.create_object($sformatf("player_%0d", action.index));
    if (object_value == null || !$cast(seq_handle, object_value)) begin
      receipt = npu_player_receipt::failure(NP_EXEC_ERROR,
          $sformatf("op %s sequence factory did not create a sequence", action.op));
      return;
    end
    if (!$cast(cmd_sequence, seq_handle)) begin
      receipt = npu_player_receipt::failure(NP_EXEC_ERROR,
          $sformatf("op %s sequence must extend npu_player_cmd_sequence", action.op));
      return;
    end
    runtime.current_action = action;
    cmd_sequence.set_action(action);
    seq_handle.start(sequencer);
    if (cmd_sequence.last_receipt == null) begin
      receipt = npu_player_receipt::failure(NP_EXEC_ERROR,
          $sformatf("op %s sequence returned no receipt", action.op));
      return;
    end
    receipt = cmd_sequence.last_receipt;
  endtask

  protected task execute_direct(npu_player_action action, output npu_player_receipt receipt);
    npu_player_mem_result result;
    if (action.kind == NP_ACT_MEM_INIT) begin
      npu_player_mem_init request = new();
      string request_error;
      if (!request.from_action(action, playback.base_dir, request_error)) begin
        receipt = npu_player_receipt::failure(NP_EXEC_ERROR, request_error);
        return;
      end
      runtime.memory.init(request, result);
      to_receipt(result, "memory_init_complete", receipt);
      return;
    end
    if (action.kind == NP_ACT_MEM_SCRUB) begin
      npu_player_mem_scrub request = new();
      string request_error;
      if (!request.from_action(action, request_error)) begin
        receipt = npu_player_receipt::failure(NP_EXEC_ERROR, request_error);
        return;
      end
      runtime.memory.scrub(request, result);
      to_receipt(result, "memory_scrub_complete", receipt);
      return;
    end
    receipt = npu_player_receipt::failure(NP_EXEC_ERROR,
        $sformatf("unsupported direct op %s", action.op));
  endtask

  protected function void to_receipt(npu_player_mem_result result, string phase,
                                     output npu_player_receipt receipt);
    if (result == null) begin
      receipt = npu_player_receipt::failure(NP_EXEC_ERROR, "memory backend returned null");
      return;
    end
    if (!result.ok) begin
      receipt = npu_player_receipt::failure(NP_EXEC_ERROR, result.error);
      return;
    end
    receipt = npu_player_receipt::success(phase, result.handle,
                                          runtime.clock_service.epoch());
  endfunction

  //===========================================================================
  // Time bases, watchdog and shutdown
  //===========================================================================
  protected task run_global_timeout();
    #(cfg.run_timeout);
    if (!stop_requested)
      fail(NP_TIMEOUT, $sformatf("run_timeout (%0t) exceeded", cfg.run_timeout));
  endtask

  protected task cycle_watchdogs();
    npu_player_receipt clock_receipt;
    realtime previous;
    forever begin
      previous = $realtime;
      runtime.clock_service.tick(clock_receipt);
      if (clock_receipt == null || !clock_receipt.ok()) begin
        fail(clock_receipt == null ? NP_EXEC_ERROR : clock_receipt.status,
             clock_receipt == null ? "clock tick returned null" : clock_receipt.error);
        return;
      end
      if ($realtime <= previous) begin
        fail(NP_EXEC_ERROR, "clock tick did not advance simulation time");
        return;
      end
      #0;
      if (runtime.clock_service.epoch() != consumer_reset_epoch) begin
        fail(NP_TIMEOUT, "reset occurred while watchdogs were armed");
        return;
      end
      command_clock_ticks++;
      foreach (watchdog_deadline_by_action[index])
        if (command_clock_ticks >= watchdog_deadline_by_action[index]) begin
          fail(NP_TIMEOUT, $sformatf("watchdog expired for action %0d", index));
          return;
        end
    end
  endtask

  protected function void dispatch_watchdog_epoch_begin();
    watchdog_deadline_by_action.delete();
  endfunction

  task request_stop_once();
    npu_player_receipt receipt;
    if (stop_requested) return;
    stop_requested = 1;
    if (status == NP_SUCCESS)
      trace_event("env.STOP", "EOF; stop new background work");
    else
      trace_event("env.STOP", {"error: ", error});
    foreach (shutdown_targets[i]) begin
      if (stopped.exists(shutdown_targets[i])) continue;
      stopped[shutdown_targets[i]] = 1;
      stop_target(shutdown_targets[i], receipt);
      if (receipt == null || !receipt.ok())
        fail(receipt == null ? NP_EXEC_ERROR : receipt.status,
             $sformatf("stop_target(%s) failed", shutdown_targets[i]));
    end
  endtask

  protected task finish_targets();
    npu_player_receipt receipt;
    foreach (shutdown_targets[i]) begin
      if (drained.exists(shutdown_targets[i])) continue;
      drained[shutdown_targets[i]] = 1;
      drain_target(shutdown_targets[i], receipt);
      if (receipt == null || !receipt.ok())
        fail(receipt == null ? NP_EXEC_ERROR : receipt.status,
             $sformatf("drain_target(%s) failed", shutdown_targets[i]));
    end
    foreach (shutdown_targets[i]) begin
      if (finished.exists(shutdown_targets[i])) continue;
      finished[shutdown_targets[i]] = 1;
      finish_target(shutdown_targets[i], receipt);
      if (receipt == null || !receipt.ok())
        fail(receipt == null ? NP_EXEC_ERROR : receipt.status,
             $sformatf("finish_target(%s) failed", shutdown_targets[i]));
    end
  endtask

  virtual task stop_target(string name, output npu_player_receipt receipt);
    receipt = npu_player_receipt::failure(NP_EXEC_ERROR,
        $sformatf("stop_target(%s) not implemented", name));
  endtask

  virtual task drain_target(string name, output npu_player_receipt receipt);
    receipt = npu_player_receipt::failure(NP_EXEC_ERROR,
        $sformatf("drain_target(%s) not implemented", name));
  endtask

  virtual task finish_target(string name, output npu_player_receipt receipt);
    receipt = npu_player_receipt::failure(NP_EXEC_ERROR,
        $sformatf("finish_target(%s) not implemented", name));
  endtask

  //===========================================================================
  // Trace and result
  //===========================================================================
  protected function void open_trace();
    trace_fd = $fopen(cfg.trace_file, "w");
    if (trace_fd == 0) begin
      `uvm_warning("NPU_PLAYER", $sformatf("cannot open trace file %s", cfg.trace_file))
      cfg.trace_file = "-";
      return;
    end
    $fdisplay(trace_fd, "# npu_player trace v2");
  endfunction

  function void trace_event(string tag, string details);
    string normalized;
    normalized = norm_tag(tag);
    if (trace_fd != 0)
      $fdisplay(trace_fd, "%0t\t%s\t%s", $realtime, normalized, details);
    if (trace_hook != null)
      trace_hook.write_snapshot(normalized, details);
  endfunction

  // Initial mapping of external tag families onto the player's single lane.
  protected function string norm_tag(string tag);
    if (npu_player_text::starts_with(tag, "disp:"))
      return {"disp.", tag.substr(5, tag.len() - 1)};
    if (npu_player_text::starts_with(tag, "m:"))
      return {"mon.", tag.substr(2, tag.len() - 1)};
    if (npu_player_text::starts_with(tag, "tmu_tmu_obs.m:"))
      return {"tmu.", tag.substr(14, tag.len() - 1)};
    if (npu_player_text::starts_with(tag, "xbar:"))
      return {"xbar.", tag.substr(5, tag.len() - 1)};
    if (npu_player_text::starts_with(tag, "axi1lane:"))
      return {"axi1lane.", tag.substr(9, tag.len() - 1)};
    if (tag == "glsu_local")
      return "glsu.axi";
    return tag;
  endfunction

  protected function void save_result();
    int fd;
    string escaped;
    if (result_saved) return;
    result_saved = 1;
    if (cfg.result_file == "-" || cfg.result_file == "") return;
    fd = $fopen(cfg.result_file, "w");
    if (fd == 0) begin
      `uvm_warning("NPU_PLAYER", $sformatf("cannot open result file %s", cfg.result_file))
      return;
    end
    escaped = escape_quotes(error);
    $fdisplay(fd, "{\"status\":\"%s\", \"completed_actions\":%0d, \"error\":\"%s\"}",
              npu_player_status_name(status), completed_actions, escaped);
    $fclose(fd);
  endfunction

  protected function string escape_quotes(string value);
    string result;
    result = "";
    for (int i = 0; i < value.len(); i++) begin
      if (value[i] == 8'h22) result = {result, "'"};
      else result = {result, value[i]};
    end
    return result;
  endfunction

  protected function void fail(npu_player_status value, string message);
    if (status == NP_SUCCESS) begin
      status = value;
      error = message;
      `uvm_error("NPU_PLAYER", message)
    end
    else begin
      trace_event("SECONDARY_FAILURE",
                  $sformatf("%s: %s", npu_player_status_name(value), message));
    end
    stop_requested = 1;
  endfunction

  virtual function void final_phase(uvm_phase phase);
    uvm_report_server server;
    super.final_phase(phase);
    server = get_report_server();
    if (server != null && status == NP_SUCCESS &&
        (server.get_severity_count(UVM_ERROR) > 0 ||
         server.get_severity_count(UVM_FATAL) > 0)) begin
      status = NP_EXEC_ERROR;
      error = "UVM report errors observed during playback";
    end
    if (!result_saved) save_result();
    if (trace_fd != 0) begin
      $fclose(trace_fd);
      trace_fd = 0;
    end
  endfunction
endclass

`endif // NPU_TB_PLAYER_SVH
