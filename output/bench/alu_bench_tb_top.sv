// Testbench Top: alu_bench_tb_top
// Data-driven generated from bench YAML configuration.
module alu_bench_tb_top;
  import uvm_pkg::*;
  import alu_test_pkg::*;

  // ── Clock & Reset Generation ──
  reg clk = 0;
  reg rst_n = 0;
  always #5ns clk = ~clk;

  // ── Wire Declarations ──
  wire [31:0] alu_a;
  wire [31:0] alu_b;
  wire [3:0] alu_op;
  wire [31:0] alu_result;
  wire [63:0] alu_result_wide;
  wire alu_valid_in;
  wire alu_ready;
  wire alu_valid_out;
  wire [3:0] alu_flags;
  wire alu_out_ready_tie;

  // ── Continuous Assignments ──
  assign alu_out_ready_tie = 1'b0;
  assign alu_result_wide = {32'b0, alu_result};

  // ── Interface Instances ──
  ALU_in_interface ALU_in_if (
    .clk(clk),
    .rst(rst_n),
    .a(alu_a),
    .b(alu_b),
    .op(alu_op),
    .valid(alu_valid_in),
    .ready(alu_ready),
    .result(alu_result_wide)
  );
  ALU_out_interface ALU_out_if (
    .clk(clk),
    .rst(rst_n),
    .result(alu_result),
    .flags(alu_flags),
    .valid(alu_valid_out),
    .ready(alu_out_ready_tie)
  );

  // ── DUT Instantiation ──
  alu
  #(
    .DATA_WIDTH(32),
    .OP_WIDTH(4)
  )
  u_alu (
    .clk(clk),
    .rst_n(rst_n),
    .a(alu_a),
    .b(alu_b),
    .op(alu_op),
    .valid_in(alu_valid_in),
    .ready_out(alu_ready),
    .result(alu_result),
    .flags(alu_flags),
    .valid_out(alu_valid_out)
  );

  // ── UVM Configuration & Test Launch ──
  initial begin
    rst_n = ~rst_n;
    uvm_config_db #(virtual ALU_in_interface)::set(
        null, "*ALU_in_agent_h*", "vif", ALU_in_if
    );
    uvm_config_db #(virtual ALU_out_interface)::set(
        null, "*ALU_out_agent_h*", "vif", ALU_out_if
    );
    uvm_root::get().set_report_verbosity_level_hier(UVM_MEDIUM);
    uvm_root::get().set_timeout(10ms);
    run_test();
  end

  // ── Waveform Dump ──
  initial begin
    if ($test$plusargs("DUMP_WAVES")) begin
      $dumpfile("alu_bench_tb_top.fst");
      $dumpvars(0, alu_bench_tb_top);
    end
  end

  // ── Simulation Control ──
  initial begin
    #100ms;
    $display("SIM_TIMEOUT after 100ms");
    $finish;
  end
  initial begin
    forever begin
      @(uvm_report_fatal);
      #100ns;
      $finish;
    end
  end

endmodule : alu_bench_tb_top
