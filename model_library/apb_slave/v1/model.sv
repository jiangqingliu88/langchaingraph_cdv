// Golden APB Slave Reference Model v1
// ======================================
// 语义（已由定向 case 仿真验证，见 manifest.json verify 记录）：
//   写：psel && penable && pwrite → regs[paddr] = pwdata（地址越界忽略）
//   读：psel && !pwrite            → prdata = regs[paddr]（地址越界回 0）
//   复位：所有寄存器清零
// 参数化：寄存器数量 NREGS / 数据位宽 DATA_W / 地址位宽 ADDR_W
// 使用约束（黄金模型不可变）：禁止现场修改本文件；新增行为只能升版本。
module apb_slave_golden #(
    parameter int NREGS = 16,
    parameter int ADDR_W = 8,
    parameter int DATA_W = 8
) (
    input  logic              clk,
    input  logic              rst_n,
    input  logic [ADDR_W-1:0] paddr,
    input  logic [DATA_W-1:0] pwdata,
    input  logic              pwrite,
    input  logic              psel,
    input  logic              penable,
    output logic [DATA_W-1:0] prdata
);
    logic [DATA_W-1:0] regs [NREGS];

    // ── 写通路（APB 写时序）──
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int i = 0; i < NREGS; i++) regs[i] <= '0;
        end else if (psel && penable && pwrite && paddr < NREGS) begin
            regs[paddr] <= pwdata;
        end
    end

    // ── 读通路（APB 读时序，组合）──
    always_comb begin
        prdata = '0;
        if (psel && !pwrite && paddr < NREGS) begin
            prdata = regs[paddr];
        end
    end
endmodule
