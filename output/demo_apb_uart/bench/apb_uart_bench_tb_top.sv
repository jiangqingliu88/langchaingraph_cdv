// Testbench Top: apb_uart_bench_tb_top
// Data-driven generated from bench YAML configuration.
module apb_uart_bench_tb_top;
  import uvm_pkg::*;
  import apb_uart_env_test_pkg::*;

  // ── Clock & Reset Generation ──
  reg clk = 0;
  reg rst_n = 0;
  always #5ns clk = ~clk;

  // ── Wire Declarations ──
  wire [31:0] data_in;
  wire [31:0] data_out;
  wire valid_in;
  wire ready_in;
  wire valid_out;
  wire ready_out;

  // ── Continuous Assignments ──
  assign ready_out = 1'b0;

  // ── Interface Instances ──
  apb_uart_in_interface apb_uart_in_if (
    .clk(clk),
    .rst(rst_n),
    .data(data_in),
    .valid(valid_in),
    .ready(ready_in)
  );
  apb_uart_out_interface apb_uart_out_if (
    .clk(clk),
    .rst(rst_n),
    .data(data_out),
    .valid(valid_out),
    .ready(ready_out)
  );

  // ── DUT Instantiation ──
  apb_uart
  #(
    .DATA_WIDTH(32)
  )
  u_apb_uart (
    .clk(clk),
    .rst_n(rst_n),
    .data_in(data_in),
    .valid_in(valid_in),
    .ready_in(ready_in),
    .data_out(data_out),
    .valid_out(valid_out),
    .ready_out(ready_out)
  );

  // ── UVM Configuration & Test Launch ──
  initial begin
    rst_n = ~rst_n;
    uvm_config_db #(virtual apb_uart_in_interface)::set(
        null, "*apb_uart_in_agent_h*", "vif", apb_uart_in_if
    );
    uvm_config_db #(virtual apb_uart_out_interface)::set(
        null, "*apb_uart_out_agent_h*", "vif", apb_uart_out_if
    );
    uvm_root::get().set_timeout(10ms);
    run_test();
  end

  // ── Waveform Dump ──

  // ── Simulation Control ──

endmodule : apb_uart_bench_tb_top
