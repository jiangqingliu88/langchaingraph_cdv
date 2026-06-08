// 自动生成的 Interface: ALU_in
interface ALU_in_interface #(
  parameter int ALU_WIDTH = 32,
  parameter int ALU_OP_WIDTH = 4
) (input  logic clk,input  logic rst,output logic [ALU_WIDTH-1:0] a,output logic [ALU_WIDTH-1:0] b,output logic [ALU_OP_WIDTH-1:0] op,output logic valid,input  logic ready,input  logic [2*ALU_WIDTH-1:0] result
);

  // HDL 类型定义
  typedef enum logic [2:0] {ADD=3'b000, SUB=3'b001, MUL=3'b010} alu_op_t;
  typedef logic [ALU_WIDTH-1:0] alu_data_t;

  // 时钟块
  clocking cb @(posedge clk);output a;output b;output op;output valid;input ready;input result;
  endclocking : cb

  // Modport
  modport mp (
    input  clk,
    input  rst,output a,output b,output op,output valid,input ready,input result,
    clocking cb
  );

  // 复位断言电平:  (可用于驱动逻辑)

endinterface : ALU_in_interface