// ════════════════════════════════════════════════════════════════
// apb_slave_dut —— APB 从机 + 寄存器堆（示例 DUT）
//
// 存在的理由：寄存器测试（`uvm_reg_hw_reset_seq` / `uvm_reg_bit_bash_seq` /
// `uvm_reg_access_seq`）要有**真寄存器**可测。这个 DUT 就是那批寄存器的最小实现，
// 与 `apb_ral_pkg.sv` 里的寄存器模型**一一对应**。
//
// 端口与 `apb/apb_interface.yaml` 一致（pclk/presetn + APB 标准 8 根）。
//
// 协议：标准 APB，**0 等待**（pready 恒 1）——
//   setup 拍 : psel=1, penable=0，地址/写数据已就位
//   access 拍: psel=1, penable=1 → 本拍完成，pready=1
//   非法地址 : pslverr=1（读回 0，写不动）
//
// ── 寄存器表（与 RAL 对齐，改一处必须改两处）──
//   0x00 CTRL     RW  en[0] mode[3:1] div[15:8]     保留位 [7:4][31:16] 恒 0
//   0x04 STATUS   RO  busy[0] err[1] state[7:4]     只读，硬件驱动
//   0x08 DATA     RW  [31:0]                        整字
//   0x0C SCRATCH  RW  [31:0]                        整字
//
// **为什么这样分 RW/RO**：`uvm_reg_bit_bash_seq` 逐位翻的是**可写位**，
// 只读寄存器整个跳过。留一个 STATUS 是为了让"只读"这件事在环境里真的存在 ——
// 全是 RW 的 DUT 测不出"模型把 RO 写坏了"这类错。
// ════════════════════════════════════════════════════════════════

module apb_slave_dut (
  input  logic        pclk,
  input  logic        presetn,      // 低有效

  // ── APB 从机侧 ──
  input  logic        psel,
  input  logic        penable,
  input  logic        pwrite,
  input  logic [31:0] paddr,
  input  logic [31:0] pwdata,
  output logic [31:0] prdata,
  output logic        pready,
  output logic        pslverr
);

  // ── 地址译码（字对齐）──
  localparam logic [31:0] ADDR_CTRL    = 32'h00;
  localparam logic [31:0] ADDR_STATUS  = 32'h04;
  localparam logic [31:0] ADDR_DATA    = 32'h08;
  localparam logic [31:0] ADDR_SCRATCH = 32'h0C;

  // ── 寄存器 ──
  logic [31:0] ctrl;      // 0x00  RW
  logic [31:0] status;    // 0x04  RO
  logic [31:0] data;      // 0x08  RW
  logic [31:0] scratch;   // 0x0C  RW

  // 一拍访问：psel + penable 同时高才是真正的访问拍
  wire access = psel && penable;
  wire wr     = access &&  pwrite;

  wire addr_hit = (paddr == ADDR_CTRL) || (paddr == ADDR_STATUS) ||
                  (paddr == ADDR_DATA) || (paddr == ADDR_SCRATCH);

  // ── 写 ──
  // 只写**可写**寄存器：STATUS 是 RO，非法地址忽略（并记一笔 err）。
  always_ff @(posedge pclk or negedge presetn) begin
    if (!presetn) begin
      ctrl    <= 32'h0;
      data    <= 32'h0;
      scratch <= 32'h0;
      status  <= 32'h0;
    end else begin
      // STATUS 由硬件驱动（只读 —— 总线写不动它）
      status[0]   <= 1'b0;                      // busy：0 等待，永远不忙
      status[7:4] <= status[7:4] + 4'd1;        // state：自由计数器，让 RO 有"活"
      if (access && !addr_hit)
        status[1] <= 1'b1;                      // err：非法地址访问 → 粘住

      if (wr) begin
        case (paddr)
          // **CTRL 必须按建模位掩码**：RAL 只建模了 en[0] / mode[3:1] / div[15:8]，
          // 位 4~7 与 16~31 是保留位。原实现 `ctrl <= pwdata` 把**整字**都存了 ——
          // `uvm_reg_bit_bash_seq` 对**没建模的位**按"硬件控制(HW)"处理：它把整字
          // 写下去、却期望那几位**不变**（保持 0）。存整字 → 读回 0x10，模型期望 0x0
          //   "Writing a 1 in bit #4 of register ctrl ... yielded 'h10 instead of 'h0"
          // 掩码后两边一致：保留位恒 0，建模位正常可写。
          ADDR_CTRL:    ctrl    <= pwdata & 32'h0000_FF0F;
          ADDR_DATA:    data    <= pwdata;      // 全 32 位 RW，不掩
          ADDR_SCRATCH: scratch <= pwdata;      // 全 32 位 RW，不掩
          default:      ;                       // STATUS / 非法地址：写不动
        endcase
      end
    end
  end

  // ── 读 ──
  // 0 等待：access 拍就要给出数据，所以是组合读。
  always_comb begin
    case (paddr)
      ADDR_CTRL:    prdata = ctrl;
      ADDR_STATUS:  prdata = status;
      ADDR_DATA:    prdata = data;
      ADDR_SCRATCH: prdata = scratch;
      default:      prdata = 32'h0;             // 非法地址读 0
    endcase
  end

  // ── 完成 / 错误 ──
  assign pready  = 1'b1;                        // 0 等待
  assign pslverr = access && !addr_hit;         // 只有非法地址报错

endmodule : apb_slave_dut
