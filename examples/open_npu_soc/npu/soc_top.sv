// Open NPU SoC v0.1 顶层。
//
// 数据流（与 verification_plan.yaml 的验收路径一致）：
//   TB 预装 A/B 到 SRAM → CPU/NICE 发 start → DMA load → GEMM → DMA store →
//   SRAM C → IRQ → TB 读取 C 并与 golden 比较。
//
// 真实 E203/NICE/AXI 的替换点：
//   · nice_cmd_sequencer 换成 E203 NICE 适配层；
//   · sram_banked 换成 banked SRAM/总线；
//   · dma_simple 换成多通道 DMA。
// 顶层端口与 TB 的比较逻辑保持不变。
`timescale 1ns/1ps

module soc_top #(
    parameter int M = 8,
    parameter int N = 8,
    parameter int K = 8
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         start,

    input  logic         tb_we,
    input  logic [1:0]   tb_bank,
    input  logic [5:0]   tb_addr,
    input  logic [31:0]  tb_wdata,

    output logic         irq,
    output logic         done,
    output logic [31:0]  c_flat [0:M*N-1]
);

    logic [7:0]  a_flat [0:M*K-1];
    logic [7:0]  b_flat [0:K*N-1];

    logic signed [7:0]  a_buf [0:M-1][0:K-1];
    logic signed [7:0]  b_buf [0:K-1][0:N-1];
    logic signed [31:0] c_buf [0:M-1][0:N-1];

    logic        dma_load;
    logic        gemm_start;
    logic        dma_store;
    logic        dma_busy;
    logic        gemm_done;
    logic        c_we;
    logic [5:0]  c_addr;
    logic [31:0] c_wdata;

    sram_banked #(.M(M), .N(N), .K(K)) u_sram (
        .clk(clk),
        .tb_we(tb_we), .tb_bank(tb_bank), .tb_addr(tb_addr), .tb_wdata(tb_wdata),
        .a_flat(a_flat), .b_flat(b_flat), .c_flat(c_flat),
        .c_we(c_we), .c_addr(c_addr), .c_wdata(c_wdata)
    );

    dma_simple #(.M(M), .N(N), .K(K)) u_dma (
        .clk(clk), .rst_n(rst_n),
        .load(dma_load), .store(dma_store),
        .a_flat(a_flat), .b_flat(b_flat),
        .a_buf(a_buf), .b_buf(b_buf), .c_in(c_buf),
        .c_we(c_we), .c_addr(c_addr), .c_wdata(c_wdata),
        .busy(dma_busy)
    );

    int8_gemm #(.M(M), .N(N), .K(K)) u_gemm (
        .clk(clk), .rst_n(rst_n), .start(gemm_start),
        .a(a_buf), .b(b_buf), .c(c_buf), .done(gemm_done)
    );

    nice_cmd_sequencer u_cmd (
        .clk(clk), .rst_n(rst_n), .start(start),
        .gemm_done(gemm_done), .dma_busy(dma_busy),
        .dma_load(dma_load), .gemm_start(gemm_start),
        .dma_store(dma_store), .irq(irq), .done(done)
    );

endmodule
