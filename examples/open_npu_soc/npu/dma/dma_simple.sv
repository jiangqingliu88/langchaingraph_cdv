// 简单 DMA —— v0.1 只负责两件事：
//   load  : SRAM A/B -> GEMM 输入缓存（一拍完成）
//   store : GEMM 输出 -> SRAM C（逐字写，busy 期间挂住）
//
// 地址映射/多通道/描述符在后续里程碑补；这里先把「DMA 参与数据搬运」这条
// 因果链接进仿真，避免 CPU/NICE 直接戳 GEMM 的内部数组。
`timescale 1ns/1ps

module dma_simple #(
    parameter int M = 8,
    parameter int N = 8,
    parameter int K = 8
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         load,
    input  logic         store,

    input  logic [7:0]   a_flat [0:M*K-1],
    input  logic [7:0]   b_flat [0:K*N-1],

    output logic signed [7:0]  a_buf [0:M-1][0:K-1],
    output logic signed [7:0]  b_buf [0:K-1][0:N-1],
    input  logic signed [31:0] c_in  [0:M-1][0:N-1],

    output logic         c_we,
    output logic [5:0]   c_addr,
    output logic [31:0]  c_wdata,
    output logic         busy
);

    logic       storing;
    logic [5:0] idx;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            storing <= 1'b0;
            idx     <= '0;
            c_we    <= 1'b0;
            c_addr  <= '0;
            c_wdata <= '0;
            for (int i = 0; i < M; i++)
                for (int k = 0; k < K; k++) a_buf[i][k] <= '0;
            for (int k = 0; k < K; k++)
                for (int j = 0; j < N; j++) b_buf[k][j] <= '0;
        end else begin
            c_we <= 1'b0;

            if (load) begin
                for (int i = 0; i < M; i++)
                    for (int k = 0; k < K; k++)
                        a_buf[i][k] <= signed'(a_flat[i*K + k]);
                for (int k = 0; k < K; k++)
                    for (int j = 0; j < N; j++)
                        b_buf[k][j] <= signed'(b_flat[k*N + j]);
            end

            if (store) begin
                storing <= 1'b1;
                idx     <= '0;
            end

            if (storing) begin
                c_we    <= 1'b1;
                c_addr  <= idx;
                c_wdata <= c_in[idx / N][idx % N];
                if (idx == M*N - 1) storing <= 1'b0;
                else                idx     <= idx + 1'b1;
            end
        end
    end

    assign busy = storing;

endmodule
