// INT8 GEMM —— C[M][N] = A[M][K] * B[K][N]，32-bit 累加。
//
// v0.1 用组合乘加（仿真验证友好）；真实 NPU 的流水化/分块/tiling 在后续版本。
`timescale 1ns/1ps

module int8_gemm #(
    parameter int M = 8,
    parameter int N = 8,
    parameter int K = 8
) (
    input  logic               clk,
    input  logic               rst_n,
    input  logic               start,

    input  logic signed [7:0]  a [0:M-1][0:K-1],
    input  logic signed [7:0]  b [0:K-1][0:N-1],
    output logic signed [31:0] c [0:M-1][0:N-1],
    output logic               done
);

    always_comb begin
        for (int i = 0; i < M; i++) begin
            for (int j = 0; j < N; j++) begin
                c[i][j] = 32'sd0;
                for (int k = 0; k < K; k++)
                    c[i][j] += a[i][k] * b[k][j];
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) done <= 1'b0;
        else        done <= start;
    end

endmodule
