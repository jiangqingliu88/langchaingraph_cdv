// Golden FIFO16 Reference Model v1
// ====================================
// 语义（已由定向 case 仿真验证，见 manifest.json verify 记录）：
//   16 深 8bit FIFO：wr_en 写入 / rd_en 读出（先入先出）
//   满/空标志：full / empty；满时写入 → overflow 单拍脉冲
//   同时读写：wr 优先（标准 FIFO：count = count + wr - rd）
// 参数化：DEPTH 深度 / DATA_W 数据位宽（默认 16×8）
// 使用约束（黄金模型不可变）：禁止现场修改本文件；新增行为只能升版本。
module fifo16_golden #(
    parameter int DEPTH  = 16,
    parameter int DATA_W = 8
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  wr_en,
    input  logic [DATA_W-1:0]     wdata,
    input  logic                  rd_en,
    output logic [DATA_W-1:0]     rdata,
    output logic                  full,
    output logic                  empty,
    output logic                  overflow
);
    logic [DATA_W-1:0] mem [DEPTH];
    int unsigned head, tail, count;
    logic overflow_p;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            head <= 0;
            tail <= 0;
            count <= 0;
            overflow_p <= 1'b0;
        end else begin
            overflow_p <= 1'b0;
            if (wr_en && rd_en && !full && !empty) begin
                // 同时读写（不满不空）：count 不变
                mem[head] <= wdata;
                head <= (head + 1) % DEPTH;
                tail <= (tail + 1) % DEPTH;
            end else if (wr_en && !full) begin
                mem[head] <= wdata;
                head <= (head + 1) % DEPTH;
                count <= count + 1;
            end else if (rd_en && !empty) begin
                tail <= (tail + 1) % DEPTH;
                count <= count - 1;
            end
            if (wr_en && full) overflow_p <= 1'b1;   // 满时写入 → overflow
        end
    end

    assign full    = (count == DEPTH);
    assign empty   = (count == 0);
    assign rdata   = mem[tail];
    assign overflow = overflow_p;
endmodule
