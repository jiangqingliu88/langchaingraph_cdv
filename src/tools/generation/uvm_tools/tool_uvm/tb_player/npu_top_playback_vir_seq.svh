//-----------------------------------------------------------------------------
// npu_top_playback_vir_seq.svh
//
// The only entry point: holds the phase objection, obtains the player, runs
// preflight and play, and turns a non-success status into a UVM_ERROR.
//-----------------------------------------------------------------------------
`ifndef NPU_TOP_PLAYBACK_VIR_SEQ_SVH
`define NPU_TOP_PLAYBACK_VIR_SEQ_SVH

class npu_top_playback_vir_seq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(npu_top_playback_vir_seq)

  npu_tb_player player;

  function new(string name = "npu_top_playback_vir_seq");
    super.new(name);
  endfunction

  function void set_player(npu_tb_player value);
    player = value;
  endfunction

  virtual task body();
    string preflight_error;
    bit found;
    uvm_test_done.raise_objection(this);
    if (player == null)
      found = uvm_config_db#(npu_tb_player)::get(null, get_full_name(), "player", player);
    if (player == null)
      found = uvm_config_db#(npu_tb_player)::get(null, "*", "player", player);
    if (player == null) begin
      `uvm_fatal("NPU_PLAYBACK", "no npu_tb_player injected (config_db key 'player')")
    end
    if (!player.preflight(preflight_error)) begin
      `uvm_fatal("NPU_PLAYBACK", {"player preflight failed: ", preflight_error})
    end
    player.play();
    if (player.status != NP_SUCCESS) begin
      `uvm_error("NPU_PLAYBACK",
                 $sformatf("playback finished with %s: %s",
                           npu_player_status_name(player.status), player.error))
    end
    uvm_test_done.drop_objection(this);
  endtask
endclass

`endif // NPU_TOP_PLAYBACK_VIR_SEQ_SVH
