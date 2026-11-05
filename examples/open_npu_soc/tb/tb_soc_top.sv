// Open NPU SoC v0.1 自检 TB。
//
// 两条路径共用本 TB：
//   1. 参考路径（默认）：soc_top + vectors/*.hex，逐字比较 C；判据
//      mismatched=0 且打印 PASS。
//   2. E203 C 用例路径（+define+E203_C_RUN）：例化 E203 官方
//      `e203_hbirdv2/tb/tb_top.v`（只读复用，不修改 E203 源树），由它装载
//      ITCM/固件并判定 TEST_PASS / TEST_FAIL。
`timescale 1ns/1ps

`ifdef E203_C_RUN
module tb_soc_top;
    // 复用 SoC 的 tb_top：C 用例的 top 仍然是 tb_soc_top，
    // 但真正的时钟/复位/固件加载/结果判定都在 E203 tb_top 里。
    tb_top u_e203_tb_top();
endmodule
`else
module tb_soc_top;

    localparam int M = 8;
    localparam int N = 8;
    localparam int K = 8;

    logic        clk = 1'b0;
    logic        rst_n = 1'b0;
    logic        start = 1'b0;

    logic        tb_we = 1'b0;
    logic [1:0]  tb_bank = 2'd0;
    logic [5:0]  tb_addr = 6'd0;
    logic [31:0] tb_wdata = 32'd0;

    logic        irq;
    logic        done;
    logic [31:0] c_flat [0:M*N-1];

    logic [7:0]  a_mem [0:M*K-1];
    logic [7:0]  b_mem [0:K*N-1];
    logic [31:0] c_exp [0:M*N-1];

    soc_top #(.M(M), .N(N), .K(K)) dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .tb_we(tb_we), .tb_bank(tb_bank), .tb_addr(tb_addr),
        .tb_wdata(tb_wdata),
        .irq(irq), .done(done), .c_flat(c_flat)
    );

    always #5 clk = ~clk;

    integer i;
    integer mismatched;

    initial begin
        // 回归脚本从 example 根目录启动，vectors/ 就在那里
        $readmemh("vectors/a.hex", a_mem);
        $readmemh("vectors/b.hex", b_mem);
        $readmemh("vectors/c.hex", c_exp);

        rst_n = 1'b0;
        repeat (5) @(posedge clk);
        rst_n = 1'b1;

        // 预装 A/B（bank 0/1）
        for (i = 0; i < M*K; i++) begin
            tb_we = 1'b1; tb_bank = 2'd0; tb_addr = i[5:0];
            tb_wdata = {24'b0, a_mem[i]};
            @(posedge clk);
        end
        for (i = 0; i < K*N; i++) begin
            tb_we = 1'b1; tb_bank = 2'd1; tb_addr = i[5:0];
            tb_wdata = {24'b0, b_mem[i]};
            @(posedge clk);
        end
        tb_we = 1'b0;

        // CPU/NICE 发命令
        start = 1'b1;
        @(posedge clk);
        start = 1'b0;

        wait (done);
        @(posedge clk);

        mismatched = 0;
        for (i = 0; i < M*N; i++) begin
            if (c_flat[i] !== c_exp[i]) begin
                mismatched = mismatched + 1;
                $display("MISMATCH c[%0d] got=0x%08x exp=0x%08x",
                         i, c_flat[i], c_exp[i]);
            end
        end

        $display("mismatched=%0d", mismatched);
        if (mismatched == 0) $display("PASS");
        else                 $display("FAIL");
        $finish;
    end

    initial begin
        #1_000_000;
        $display("TIMEOUT waiting for done");
        $display("FAIL");
        $finish;
    end

endmodule
`endif
