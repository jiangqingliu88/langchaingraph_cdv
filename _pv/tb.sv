module tb;
  logic clk = 0, rst_n = 0;
  logic [2:0] instr_type = 0, instr_dtype = 0;
  logic [3:0] instr_opcode = 0;
  logic [1:0] barrier_type = 0, cluster_id = 0, op_priority = 0;
  logic [2:0] issue_unit; logic [1:0] issue_decision;
  npu_sched u_dut(.clk(clk), .rst_n(rst_n), .instr_type(instr_type),
    .instr_dtype(instr_dtype), .instr_opcode(instr_opcode),
    .barrier_type(barrier_type), .cluster_id(cluster_id),
    .op_priority(op_priority), .issue_unit(issue_unit),
    .issue_decision(issue_decision));
  always #1 clk = ~clk;
  initial begin
    #5 rst_n = 1;
    for (int i = 0; i < 40; i++) begin
      @(posedge clk); instr_type <= i % 4; instr_opcode <= i % 10; cluster_id <= i % 4;
    end
    #4 $finish;
  end
endmodule
