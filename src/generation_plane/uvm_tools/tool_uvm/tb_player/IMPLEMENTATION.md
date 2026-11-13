# npu_tb_player implementation notes

This directory implements the player described by [readme.md](readme.md) as a
**standalone package**. It has no dependency on the env, agents, a concrete
memory model or any other SignOffAI module.

## Files

| File | role |
| :--- | :--- |
| `npu_player_value.svh` | `npu_player_json_value/parser`, `key=value` parser, 74/75-bit container parsing |
| `npu_player_program.svh` | `npu_player_action` / `npu_player_program`; `commands.tsv` scan + `commands.json` merge |
| `npu_player_memory.svh` | `mem_init` / `mem_scrub` requests, abstract `npu_player_memory_if`, failing stub |
| `npu_player_runtime.svh` | status/receipt/observation, clock, counting event bus, cfg, runtime |
| `npu_player_trace_hook.svh` | optional trace facade the env can implement |
| `npu_player_sequence.svh` | `npu_player_cmd_sequence` + handler/validator binding contracts |
| `npu_tb_player.svh` | core coordinator: preflight, playback, watchdog, shutdown, trace, result |
| `npu_top_playback_vir_seq.svh` | entry sequence (objection holder) |
| `npu_top_player_pkg.sv` | package entry |

## Compile (QuestaSim + UVM 1.2)

```powershell
$UVM = "F:/questasim64_2024.1/verilog_src/uvm-1.2/src"
$TB  = "<repo>/src/generation_plane/uvm_tools/tool_uvm/tb_player"

vlib work
vlog -sv +incdir+$UVM +incdir+$TB "$UVM/uvm_pkg.sv" "$TB/npu_top_player_pkg.sv"
```

Simulation needs the UVM DPI library:

```powershell
vsim -sv_lib "F:/questasim64_2024.1/uvm-1.2/win64/uvm_dpi" ...
```

The package compiles with **0 errors / 0 warnings** against QuestaSim 2024.1
UVM 1.2.

## Integration points

The env (outside this directory) supplies five things; everything else is
implemented here.

1. **cfg / runtime** — `uvm_config_db#(npu_player_cfg)::set(..., "cfg", cfg)`
   and `#(npu_player_runtime)::set(..., "runtime", runtime)`. The runtime must
   carry a `npu_player_clock`, a `npu_player_event_bus` and (optionally) a
   `npu_player_memory_if`. Missing clock/memory are replaced by failing stubs.
2. **event producers** — before `preflight()`, declare every event name that
   the program waits on but does not locally `signal_event`:
   `runtime.events.declare_producer("load_complete")`. `wait_done tag=...` is
   treated as a wait on the tag event.
3. **sequence bindings** — for every hardware/external op:
   ```systemverilog
   player.bind_sequence("tld_drv_xn", sequencer, my_cmd_seq::type_id::get());
   ```
   `my_cmd_seq` extends `npu_player_cmd_sequence`, implements
   `set_action(npu_player_action)`, and on success must set `last_receipt` to
   `npu_player_receipt::success("cmd accept", <non-empty handle>, epoch, 1)`.
   The player back-checks phase/handle/epoch; anything else is `NP_EXEC_ERROR`.
4. **direct ops** — `mem_init`/`mem_scrub` call `connect_memory()`’s backend.
   A subclass claims other direct ops by overriding `validates_direct()` and
   `execute_direct()` (the base reports unsupported ops).
5. **entry** — create `npu_top_playback_vir_seq`, give it the player (directly
   via `set_player()` or config_db key `player`), and start it. It raises
   `uvm_test_done` around `preflight()` + `play()`; without that objection the
   phase can end at time 0.

Optional: `bind_handler(op, handler)`, `bind_validator(op, validator)`,
`add_shutdown_target(name)` + override `stop_target/drain_target/finish_target`,
`set_trace_hook(hook)`.

## Implemented semantics (readme §3–§9)

- **preflight** — four scans; local parsing/normalization first, external
  `validate()` second, local producer declaration last. Program limits,
  batch pairing, event deadlock, dispatch masks, raw container normalization
  and sequence/handler presence are all checked before any external effect.
- **one-shot** — `preflight()`, `bind_*()` and `play()` all reject re-entry.
- **playback** — `wait_ready`, reset-epoch checks between actions, per-action
  `action_timeout` fork, hardware receipt back-check (`cmd accept` + handle +
  epoch), observation list and `completed_actions`.
- **built-ins** — `wait_cycles`, `nop`, `signal_event`, `wait_event`,
  `wait_done` (tag alias), `checkpoint`, `watchdog`, `dispatch_mask`,
  `dispatch_skip`, `batch_begin/end`; `mem_init`/`mem_scrub` go direct.
- **time bases** — clock `wait_cycles` for business waits, clock `tick` for the
  watchdog loop; the loop also rejects a tick that does not advance
  simulation time. `watchdog_deadline_by_action` is checked each tick.
- **shutdown** — `stop -> drain-all -> finish-all`, two-phase, idempotent.
- **trace** — single writer, opened in `build_phase`; `%0t` fs timestamps,
  `env.START/END/STOP`, `SECONDARY_FAILURE`, external tags via `trace_event`
  and the injected hook.
- **result** — one JSON line:
  `{"status":"NP_SUCCESS", "completed_actions":N, "error":""}`.

## Self-check used during implementation

A temporary UVM testbench (not shipped) injected a clock, a memory backend,
generic command sequences for `npu_cfg_drv_xn/tld_drv_xn/tst_drv_xn`, and a
`sync_drv_xn` handler that publishes its tag. Against a real
`commands.tsv/commands.json` bundle (15 actions):

```
status=NP_SUCCESS completed=15 init=1 scrub=1
file=.../03_commands/data/Source.hex
UVM_ERROR : 0, UVM_FATAL : 0
```

The trace showed `cmd accept` receipts for 10 hardware rows, `event_consumed`
for both `wait_done` rows, and the two memory direct ops.

## Boundaries

- `commands.tsv` instruction rows carry `index/line/source`; the 74-bit
  `cmddata` comes from `commands.json` metadata. An instruction without
  metadata is rejected in preflight instead of silently skipping.
- Only the built-ins listed above are implemented; other control ops require a
  handler binding or a `validates_direct/execute_direct` override.
- `raw75_layout` must be `"flag_msb"` to accept the 75-bit container.
- `action_timeout`/`run_timeout` are simulation-time delays; the clock service
  must be able to service `wait_cycles` and `tick` concurrently.
