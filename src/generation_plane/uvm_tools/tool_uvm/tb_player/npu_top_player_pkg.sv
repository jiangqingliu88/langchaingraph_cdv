//-----------------------------------------------------------------------------
// npu_top_player_pkg.sv
//
// Standalone playback player package.  Compile with UVM 1.2:
//   vlog -sv +incdir+$UVM_HOME/src +incdir+<this dir> npu_top_player_pkg.sv
//-----------------------------------------------------------------------------
package npu_top_player_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "npu_player_value.svh"
  `include "npu_player_program.svh"
  `include "npu_player_memory.svh"
  `include "npu_player_runtime.svh"
  `include "npu_player_trace_hook.svh"
  `include "npu_player_sequence.svh"
  `include "npu_tb_player.svh"
  `include "npu_top_playback_vir_seq.svh"
endpackage
