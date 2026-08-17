// Golden UART TX Reference Model v1
// ====================================
// 语义（已由定向 case 仿真验证，见 manifest.json verify 记录）：
//   8N1 LSB-first 位流生成：idle=1 → 起始位(0) → 8 数据位 → 停止位(1)
//   触发：tx_start 单拍拉高 → 开始发送 tx_data（BAUD_DIV 个时钟周期/位）
// 参数化：DATA_BITS 数据位宽 / BAUD_DIV 波特率分频
// 使用约束（黄金模型不可变）：禁止现场修改本文件；新增行为只能升版本。
module uart_tx_golden #(
    parameter int DATA_BITS = 8,
    parameter int BAUD_DIV  = 10416
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  tx_start,
    input  logic [DATA_BITS-1:0]  tx_data,
    output logic                  tx,
    output logic                  tx_busy
);
    typedef enum logic [1:0] {IDLE, START, DATA, STOP} state_t;
    state_t state;
    logic [DATA_BITS-1:0] shreg;
    int unsigned cnt, bit_idx;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state  <= IDLE;
            tx     <= 1'b1;
            tx_busy<= 1'b0;
            cnt    <= 0;
            bit_idx<= 0;
        end else begin
            case (state)
                IDLE: begin
                    tx <= 1'b1;
                    tx_busy <= 1'b0;
                    if (tx_start) begin
                        shreg <= tx_data;
                        cnt   <= 0;
                        bit_idx <= 0;
                        state <= START;
                    end
                end
                START: begin
                    tx_busy <= 1'b1;
                    tx <= 1'b0;                       // 起始位
                    if (cnt == BAUD_DIV) begin cnt <= 0; state <= DATA; end
                    else cnt <= cnt + 1;
                end
                DATA: begin
                    tx <= shreg[0];                   // LSB first
                    if (cnt == BAUD_DIV) begin
                        cnt <= 0;
                        shreg <= shreg >> 1;
                        if (bit_idx == DATA_BITS - 1) state <= STOP;
                        else bit_idx <= bit_idx + 1;
                    end else cnt <= cnt + 1;
                end
                STOP: begin
                    tx <= 1'b1;                       // 停止位
                    if (cnt == BAUD_DIV) begin cnt <= 0; state <= IDLE; end
                    else cnt <= cnt + 1;
                end
            endcase
        end
    end
endmodule
