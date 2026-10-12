module npu_sched (input logic clk, input logic rst_n,
                  input logic [2:0] instr_type, input logic [2:0] instr_dtype,
                  input logic [3:0] instr_opcode, input logic [1:0] barrier_type,
                  input logic [1:0] cluster_id, input logic [2:0] op_priority,
                  output logic [2:0] issue_unit, output logic [1:0] issue_decision);
  logic [5:0] queue_level;      // 内部状态
  logic [1:0] dep_type;         // 内部状态
  logic [7:0] instr_seq;        // 派生信号（DUT 自己暴露）
  logic [2:0] pipeline_state;   // 内部状态
  always_ff @(posedge clk) if (!rst_n) begin
    queue_level <= 0; dep_type <= 0; instr_seq <= 0; pipeline_state <= 0;
  end else begin
    queue_level <= queue_level + 1;
    dep_type <= instr_type[1:0];
    instr_seq <= {instr_seq[3:0], instr_opcode};
    pipeline_state <= instr_type;
  end
  assign issue_unit = instr_type;
  assign issue_decision = queue_level[0] ? 2'd0 : 2'd1;
endmodule
