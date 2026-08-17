// Golden IRQ Generator Reference Model v1
// ==========================================
// 语义（已由定向 case 仿真验证，见 manifest.json verify 记录）：
//   源事件脉冲（irq_src）置位 pending；使能位（irq_en）控制输出
//   irq = |(pending & irq_en)；irq_clear 清零全部 pending
// 参数化：N_SRC 中断源数量
// 使用约束（黄金模型不可变）：禁止现场修改本文件；新增行为只能升版本。
module irq_gen_golden #(
    parameter int N_SRC = 4
) (
    input  logic               clk,
    input  logic               rst_n,
    input  logic [N_SRC-1:0]   irq_src,
    input  logic [N_SRC-1:0]   irq_en,
    input  logic               irq_clear,
    output logic               irq,
    output logic [N_SRC-1:0]   irq_pending
);
    logic [N_SRC-1:0] pending;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending <= '0;
        end else if (irq_clear) begin
            pending <= '0;
        end else begin
            pending <= pending | irq_src;
        end
    end

    assign irq_pending = pending;
    assign irq         = |(pending & irq_en);
endmodule
