// NICE 命令时序（v0.1 的 CPU 侧参考驱动）。
//
// 真实的 E203 在 NICE 扩展里执行自定义指令并驱动这套握手；v0.1 先用一个
// 确定性状态机把「发命令 → DMA 搬数 → GEMM → IRQ」的时序钉住，供 SoC 仿真
// 和后续 UVM agent 复用。端口名刻意与 NICE 命令/响应语义对应：
//
//   start        CPU 提交一条 GEMM 命令
//   dma_load     NICE 让 DMA 把 A/B 搬进 GEMM 缓存
//   gemm_start   启动 GEMM
//   gemm_done    GEMM 完成（内部握手）
//   dma_store    DMA 把 C 写回 SRAM
//   irq          完成中断（CPU 侧可据此读结果）
`timescale 1ns/1ps

module nice_cmd_sequencer (
    input  logic clk,
    input  logic rst_n,
    input  logic start,
    input  logic gemm_done,
    input  logic dma_busy,

    output logic dma_load,
    output logic gemm_start,
    output logic dma_store,
    output logic irq,
    output logic done
);

    typedef enum logic [2:0] {
        IDLE, LOAD, LAUNCH, WAIT_GEMM, STORE, WAIT_STORE, IRQ_PULSE, DONE
    } state_t;

    state_t state;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= IDLE;
            dma_load   <= 1'b0;
            gemm_start <= 1'b0;
            dma_store  <= 1'b0;
            irq        <= 1'b0;
            done       <= 1'b0;
        end else begin
            dma_load   <= 1'b0;
            gemm_start <= 1'b0;
            dma_store  <= 1'b0;
            irq        <= 1'b0;
            done       <= 1'b0;

            case (state)
                IDLE:       if (start) state <= LOAD;
                LOAD:       begin dma_load <= 1'b1; state <= LAUNCH; end
                LAUNCH:     begin gemm_start <= 1'b1; state <= WAIT_GEMM; end
                WAIT_GEMM:  if (gemm_done) state <= STORE;
                STORE:      begin dma_store <= 1'b1; state <= WAIT_STORE; end
                WAIT_STORE: if (!dma_busy) state <= IRQ_PULSE;
                IRQ_PULSE:  begin irq <= 1'b1; state <= DONE; end
                DONE:       begin done <= 1'b1; state <= IDLE; end
                default:    state <= IDLE;
            endcase
        end
    end

endmodule
