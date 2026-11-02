// Banked SRAM —— v0.1 只做仿真用的小容量模型。
//
// A/B 各 64 字节（8x8 INT8），C 64 个 32-bit 字（8x8 INT32）。
// TB 通过 tb_* 端口预装 A/B；DMA 通过 c_* 端口回写 C。
// 这不是可综合的 banked SRAM 生成器，只是把地址/时序契约钉下来。
`timescale 1ns/1ps

module sram_banked #(
    parameter int M = 8,
    parameter int N = 8,
    parameter int K = 8
) (
    input  logic         clk,

    // testbench 预装端口：bank 0=A, 1=B
    input  logic         tb_we,
    input  logic [1:0]   tb_bank,
    input  logic [5:0]   tb_addr,
    input  logic [31:0]  tb_wdata,

    output logic [7:0]   a_flat [0:M*K-1],
    output logic [7:0]   b_flat [0:K*N-1],
    output logic [31:0]  c_flat [0:M*N-1],

    // DMA 回写 C
    input  logic         c_we,
    input  logic [5:0]   c_addr,
    input  logic [31:0]  c_wdata
);

    always_ff @(posedge clk) begin
        if (tb_we) begin
            if (tb_bank == 2'd0)      a_flat[tb_addr] <= tb_wdata[7:0];
            else if (tb_bank == 2'd1) b_flat[tb_addr] <= tb_wdata[7:0];
        end
        if (c_we) c_flat[c_addr] <= c_wdata;
    end

endmodule
