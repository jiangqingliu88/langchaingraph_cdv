//-----------------------------------------------------------------------------
// npu_player_runtime.svh
//
// Runtime contract shared by the player and the env: status, receipt, clock,
// event bus, configuration and the runtime bundle.  No env type is referenced.
//-----------------------------------------------------------------------------
`ifndef NPU_PLAYER_RUNTIME_SVH
`define NPU_PLAYER_RUNTIME_SVH

typedef enum {
  NP_SUCCESS,
  NP_INPUT_ERROR,
  NP_BLOCKED,
  NP_TIMEOUT,
  NP_EXEC_ERROR,
  NP_MODEL_LIMIT
} npu_player_status;

function automatic string npu_player_status_name(npu_player_status status);
  case (status)
    NP_SUCCESS     : return "NP_SUCCESS";
    NP_INPUT_ERROR : return "NP_INPUT_ERROR";
    NP_BLOCKED     : return "NP_BLOCKED";
    NP_TIMEOUT     : return "NP_TIMEOUT";
    NP_EXEC_ERROR  : return "NP_EXEC_ERROR";
    NP_MODEL_LIMIT : return "NP_MODEL_LIMIT";
    default        : return "NP_UNKNOWN";
  endcase
endfunction

//=============================================================================
// npu_player_receipt - "this action may advance", not "the DUT retired it"
//=============================================================================
class npu_player_receipt;
  npu_player_status status;
  string           handle;
  string           phase;
  longint unsigned epoch;
  bit              is_hardware;
  string           error;

  function new();
    status = NP_SUCCESS;
    handle = "";
    phase = "";
    epoch = 0;
    is_hardware = 0;
    error = "";
  endfunction

  static function npu_player_receipt success(string phase, string handle,
                                             longint unsigned epoch,
                                             bit is_hardware = 0);
    npu_player_receipt r = new();
    r.status = NP_SUCCESS;
    r.phase = phase;
    r.handle = handle;
    r.epoch = epoch;
    r.is_hardware = is_hardware;
    return r;
  endfunction

  static function npu_player_receipt failure(npu_player_status status, string error,
                                             longint unsigned epoch = 0);
    npu_player_receipt r = new();
    r.status = status;
    r.error = error;
    r.phase = "";
    r.handle = "";
    r.epoch = epoch;
    r.is_hardware = 0;
    return r;
  endfunction

  function bit ok();
    return status == NP_SUCCESS;
  endfunction
endclass

class npu_player_observation;
  npu_player_action  action;
  npu_player_receipt receipt;

  function new(npu_player_action action, npu_player_receipt receipt);
    this.action = action;
    this.receipt = receipt;
  endfunction
endclass

//=============================================================================
// npu_player_clock - injected by env
//=============================================================================
virtual class npu_player_clock;
  // Ready to accept work (env assembled, reset released).
  pure virtual task wait_ready(output npu_player_receipt receipt);
  // Business wait; may be aborted by reset.
  pure virtual task wait_cycles(longint unsigned count, output npu_player_receipt receipt);
  // Independent tick; must not be aborted by reset (watchdog/run timeout).
  pure virtual task tick(output npu_player_receipt receipt);
  pure virtual function longint unsigned epoch();
endclass

class npu_player_clock_stub extends npu_player_clock;
  virtual task wait_ready(output npu_player_receipt receipt);
    receipt = npu_player_receipt::failure(NP_BLOCKED,
        "no clock service bound: inject npu_player_clock into the runtime");
  endtask

  virtual task wait_cycles(longint unsigned count, output npu_player_receipt receipt);
    receipt = npu_player_receipt::failure(NP_BLOCKED,
        "no clock service bound: inject npu_player_clock into the runtime");
  endtask

  virtual task tick(output npu_player_receipt receipt);
    receipt = npu_player_receipt::failure(NP_BLOCKED,
        "no clock service bound: inject npu_player_clock into the runtime");
  endtask

  virtual function longint unsigned epoch();
    return 0;
  endfunction
endclass

//=============================================================================
// npu_player_event_bus - counting events, not pulses
//=============================================================================
class npu_player_event_bus;
  protected string           external_producers[string];
  protected string           local_producers[string];
  protected int unsigned     counts[string];
  protected longint unsigned bus_epoch;

  function new();
    bus_epoch = 0;
  endfunction

  function void declare_producer(string name);
    external_producers[name] = name;
  endfunction

  function void declare_local_producer(string name);
    local_producers[name] = name;
  endfunction

  function bit is_declared(string name);
    return external_producers.exists(name) || local_producers.exists(name);
  endfunction

  function bit has_external_producer(string name);
    return external_producers.exists(name);
  endfunction

  function bit publish(string name, output string error);
    if (!is_declared(name)) begin
      error = {"unregistered event producer: ", name};
      return 0;
    end
    counts[name] = (counts.exists(name) ? counts[name] : 0) + 1;
    error = "";
    return 1;
  endfunction

  function int unsigned count(string name);
    return counts.exists(name) ? counts[name] : 0;
  endfunction

  function longint unsigned epoch();
    return bus_epoch;
  endfunction

  // A reset advances the epoch, clears counts and keeps producer registrations.
  function void set_epoch(longint unsigned value);
    bus_epoch = value;
    counts.delete();
  endfunction

  function void clear_counts();
    counts.delete();
  endfunction
endclass

//=============================================================================
// npu_player_cfg
//=============================================================================
class npu_player_cfg;
  string           commands_file = "-";
  string           metadata_file = "-";
  int              core_id = 0;
  string           isa_revision_allow = "ISA_VERSION_V1.4";
  string           address_schema_allow = "GLOBAL48_V1.4";
  string           raw75_layout = "unspecified";   // "unspecified" | "flag_msb"
  longint unsigned default_event_timeout_cycles = 100000;
  time             action_timeout = 1ms;
  time             finish_timeout = 1ms;
  time             run_timeout = 1s;
  int unsigned     max_file_bytes = 64 * 1024 * 1024;
  int unsigned     max_actions = 1000000;
  int unsigned     max_event_names = 4096;
  string           trace_file = "-";
  string           result_file = "-";

  function void copy_from(npu_player_cfg other);
    if (other == null) return;
    commands_file = other.commands_file;
    metadata_file = other.metadata_file;
    core_id = other.core_id;
    isa_revision_allow = other.isa_revision_allow;
    address_schema_allow = other.address_schema_allow;
    raw75_layout = other.raw75_layout;
    default_event_timeout_cycles = other.default_event_timeout_cycles;
    action_timeout = other.action_timeout;
    finish_timeout = other.finish_timeout;
    run_timeout = other.run_timeout;
    max_file_bytes = other.max_file_bytes;
    max_actions = other.max_actions;
    max_event_names = other.max_event_names;
    trace_file = other.trace_file;
    result_file = other.result_file;
  endfunction
endclass

//=============================================================================
// npu_player_runtime - what the env installs and the player consumes
//=============================================================================
class npu_player_runtime;
  npu_player_cfg          cfg;
  npu_player_clock        clock_service;
  npu_player_event_bus    events;
  npu_player_memory_if    memory;
  npu_player_action       current_action;

  function new();
    events = new();
    clock_service = null;
    memory = null;
    cfg = null;
  endfunction

  function void ensure_defaults();
    if (events == null) events = new();
    if (clock_service == null) clock_service = npu_player_clock_stub::new();
    if (memory == null) memory = npu_player_memory_stub::new();
  endfunction
endclass

`endif // NPU_PLAYER_RUNTIME_SVH
