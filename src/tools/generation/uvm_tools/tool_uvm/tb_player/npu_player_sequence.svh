//-----------------------------------------------------------------------------
// npu_player_sequence.svh
//
// The three binding shapes the player accepts:
//   · npu_player_cmd_sequence - a UVM sequence that receives the action and
//     leaves a receipt behind (the normal command path);
//   · npu_player_op_handler  - a non-sequence executor (direct/peer ops);
//   · npu_player_op_validator- read-only preflight validation for an op.
//
// Agent sequences extend npu_player_cmd_sequence; their concrete item type is
// created inside the sequence body, so the player stays item-type agnostic.
//-----------------------------------------------------------------------------
`ifndef NPU_PLAYER_SEQUENCE_SVH
`define NPU_PLAYER_SEQUENCE_SVH

virtual class npu_player_cmd_sequence extends uvm_sequence #(uvm_sequence_item);
  //: Evidence from the last start(); must be non-null on success.
  npu_player_receipt last_receipt;

  function new(string name = "npu_player_cmd_sequence");
    super.new(name);
    last_receipt = null;
  endfunction

  //: Called by the player before start().
  pure virtual function void set_action(npu_player_action action);

  //: Read-only preflight hook.  Default accepts.
  virtual function bit validate_action(npu_player_action action, output string error);
    error = "";
    return 1;
  endfunction
endclass

virtual class npu_player_op_validator;
  pure virtual function bit validate(npu_player_action action, output string error);
endclass

virtual class npu_player_op_handler extends npu_player_op_validator;
  pure virtual task execute(npu_player_action action,
                            output npu_player_receipt receipt);
endclass

`endif // NPU_PLAYER_SEQUENCE_SVH
