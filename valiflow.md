---
agent_hints: {}
project: ALU_IP
spec: specs/alu/alu_chip_spec.md
---

## constraints
  - alu_data_width: 32
  - alu_op_count: 13
  - target_freq: 500MHz
  - process_node: 28nm

## fi_profile
  - targets: [flag_N, flag_Z, flag_C, flag_V, apb_config]
  - asil_target: B

## known_issues
  - "loopback matched=0: driver not asserting valid signal, fixed in template"
  - "compile error UVM_FINISHED: UVM-1.1d compat, removed from sequencer template"
  - "result port mismatch: input port included in exp copy, fixed to output-only"
