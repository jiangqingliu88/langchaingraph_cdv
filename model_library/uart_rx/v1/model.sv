// Golden UART RX Reference Model v1
// ====================================
// 语义（已由定向 case 仿真验证，见 manifest.json verify 记录）：
//   8N1 LSB-first 采样恢复：检测起始位下降沿 → 中点采样 8 数据位 → 停止位 → rx_valid 脉冲
// 参数化：DATA_BITS 数据位宽 / BAUD_DIV 波特率分频
// 使用约束（黄金模型不可变）：禁止现场修改本文件；新增行为只能升版本。
module uart_rx_golden #(
    parameter int DATA_BITS = 8,
    parameter int BAUD_DIV  = 10416
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  rx,
    output logic [DATA_BITS-1:0]  rx_data,
    output logic                  rx_valid
);
    typedef enum logic [1:0] {IDLE, START, DATA, STOP} state_t;
    state_t state;
    logic [DATA_BITS-1:0] shreg;
    int unsigned cnt, bit_idx;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= IDLE;
            rx_data <= '0;
            rx_valid<= 1'b0;
            cnt     <= 0;
            bit_idx <= 0;
        end else begin
            rx_valid <= 1'b0;
            case (state)
                IDLE: begin
                    if (!rx) begin                  // 起始位下降沿
                        cnt <= 0;
                        state <= START;
                    end
                end
                START: begin
                    if (cnt == BAUD_DIV / 2) begin  // 起始位中点采样
                        cnt <= 0;
                        bit_idx <= 0;
                        state <= DATA;
                    end else cnt <= cnt + 1;
                end
                DATA: begin
                    if (cnt == BAUD_DIV) begin
                        cnt <= 0;
                        shreg[bit_idx] <= rx;       // 数据位中点采样
                        if (bit_idx == DATA_BITS - 1) state <= STOP;
                        else bit_idx <= bit_idx + 1;
                    end else cnt <= cnt + 1;
                end
                STOP: begin
                    if (cnt == BAUD_DIV) begin
                        cnt <= 0;
                        rx_data <= shreg;
                        rx_valid <= 1'b1;
                        state <= IDLE;
                    end else cnt <= cnt + 1;
                end
            endcase
        end
    end
endmodule
