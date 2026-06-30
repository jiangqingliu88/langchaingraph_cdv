// 自动生成的 Interface: ALU_out
interface ALU_out_interface #(
  parameter int DATA_WIDTH = 32,
  parameter int FLAGS_WIDTH = 4,
  parameter int ALU_OP_WIDTH = 4
) (input  logic clk,input  logic rst,input  logic [DATA_WIDTH-1:0] result,input  logic [FLAGS_WIDTH-1:0] flags,input  logic valid,output logic ready
);

  // HDL 类型定义
  typedef struct packed { logic N; logic Z; logic C; logic V; } alu_flags_t;

  // 时钟块
  clocking cb @(posedge clk);input result;input flags;input valid;output ready;
  endclocking : cb

  // Modport
  modport mp (
    input  clk,
    input  rst,input result,input flags,input valid,output ready,
    clocking cb
  );

  // 复位断言电平:  (可用于驱动逻辑)

endinterface : ALU_out_interface