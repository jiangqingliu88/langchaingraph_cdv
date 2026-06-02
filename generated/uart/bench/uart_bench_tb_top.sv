// Testbench Top: uart_bench_tb_top
// 自动生成的 UVMF 风格测试平台顶层

module uart_bench_tb_top;

  import uvm_pkg::*;
  import uart_env_test_pkg::*;

  // ═══════════════════════════════════════════════════════════════
  // 1. Clock & Reset VIP 接口实例
  // ═══════════════════════════════════════════════════════════════
  clk_rst_if #(
    .NUM_CLKS(0),
    .NUM_RSTS(0)
  ) clk_rst_if();

  // ═══════════════════════════════════════════════════════════════
  // 2. Agent 接口实例（绑定到 VIP 信号）
  // ═══════════════════════════════════════════════════════════════

  uart_if UART_in_if (
    .clk(clk_rst_if.clk[0]),
    .rst_n(clk_rst_if.rst_n[0])
  );


  // ═══════════════════════════════════════════════════════════════
  // 3. DUT 实例
  // ═══════════════════════════════════════════════════════════════

  // ──── UVM 测试启动 ────
  initial begin
      // 设置 VIP 接口
    uvm_config_db #(virtual clk_rst_if)::set(null, "*", "vif", clk_rst_if);
    // 设置虚拟接口到 config_db

    // 设置超时时间
    uvm_root::get().set_timeout(10ms);

    // 方式1: 从命令行参数获取测试名（推荐）
    run_test();
    
    // 方式2: 硬编码默认测试名（兜底方案）
    // 如果命令行没有 +UVM_TESTNAME，则使用默认测试
    // if (!$value$plusargs("UVM_TESTNAME=%s", test_name))
    //   run_test("uart_bench_base_test");
    // else
    //   run_test();

  end

  // ──── 波形转储 ────
  initial begin
    if ($test$plusargs("DUMP_WAVES")) begin
      $dumpfile("uart_bench_tb_top.vcd");
      $dumpvars(0, uart_bench_tb_top);
    end
  end


  // ──── 结束报告 ────
  final begin
    $display("========================================");
    $display("Testbench: uart_bench_tb_top");
    $display("Test: uart_bench_base_test");
    $display("End time: %0t", $time);
    $display("========================================");
  end

endmodule : uart_bench_tb_top