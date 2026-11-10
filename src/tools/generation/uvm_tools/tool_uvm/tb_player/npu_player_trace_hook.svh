//-----------------------------------------------------------------------------
// npu_player_trace_hook.svh
//
// Facade the env may inject to fold monitor snapshots into the player's single
// trace writer.  The player package must not depend on the env package, so the
// dependency points this way: env implements, player consumes.
//-----------------------------------------------------------------------------
`ifndef NPU_PLAYER_TRACE_HOOK_SVH
`define NPU_PLAYER_TRACE_HOOK_SVH

virtual class npu_player_trace_hook;
  pure virtual function void write_snapshot(string tag, string details);
endclass

`endif // NPU_PLAYER_TRACE_HOOK_SVH
