// Interface Structure: ALU_out_struct
// 将 interface 信号封装为 struct，便于采样和传递
typedef struct packed {
  logic clk;                     // input
  logic rst;                     // input
  logic [DATA_WIDTH-1:0] result;  // input
  logic [FLAGS_WIDTH-1:0] flags;  // input
  logic valid;                     // input
  logic ready;                     // output
} ALU_out_struct_t;