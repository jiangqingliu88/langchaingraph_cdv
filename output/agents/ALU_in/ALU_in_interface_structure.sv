// Interface Structure: ALU_in_struct
// 将 interface 信号封装为 struct，便于采样和传递
typedef struct packed {
  logic clk;                     // input
  logic rst;                     // input
  logic [ALU_WIDTH-1:0] a;  // output
  logic [ALU_WIDTH-1:0] b;  // output
  logic [ALU_OP_WIDTH-1:0] op;  // output
  logic valid;                     // output
  logic ready;                     // input
  logic [2*ALU_WIDTH-1:0] result;  // input
} ALU_in_struct_t;