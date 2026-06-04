// ============================================================
// UVM 编译 filelist —— 由模板生成（绝对路径）
// ============================================================
// DUT (项目源码)
D:\cdv_a\src\tools\compilesim\dut\uart.v

// ─── Base PKG: Clock & Reset VIP ───
+incdir+D:\cdv_a\src\tools\uvm\tool_uvm\base_pkg/clk_and_rst
D:\cdv_a\src\tools\uvm\tool_uvm\base_pkg/clk_and_rst/clk_and_rst_pkg.sv

// ─── Interface ───
D:\cdv_a\generated\uart\agents/UART_in/UART_in_interface.sv
D:\cdv_a\generated\uart\agents/UART_out/UART_out_interface.sv
D:\cdv_a\generated\uart\agents/AXI_in/AXI_in_interface.sv

// ─── Agent Package ───
+incdir+D:\cdv_a\generated\uart\agents/UART_in
D:\cdv_a\generated\uart\agents/UART_in/UART_in_pkg.sv
+incdir+D:\cdv_a\generated\uart\agents/UART_out
D:\cdv_a\generated\uart\agents/UART_out/UART_out_pkg.sv
+incdir+D:\cdv_a\generated\uart\agents/AXI_in
D:\cdv_a\generated\uart\agents/AXI_in/AXI_in_pkg.sv

// ─── Environment ───
+incdir+D:\cdv_a\generated\uart\env
D:\cdv_a\generated\uart\env/uart_env_pkg.sv
+incdir+D:\cdv_a\generated\uart\env/tests
D:\cdv_a\generated\uart\env/tests/uart_env_test_pkg.sv
+incdir+D:\cdv_a\generated\uart\env/seqs
D:\cdv_a\generated\uart\env/seqs/uart_env_seq_pkg.sv

// ─── Testbench Top ───
D:\cdv_a\generated\uart\bench/uart_bench_tb_top.sv
