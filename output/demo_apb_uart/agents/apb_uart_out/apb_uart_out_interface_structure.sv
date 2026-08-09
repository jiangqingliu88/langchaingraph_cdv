// Interface Structure: apb_uart_out_struct
// 将 interface 信号封装为 struct，便于采样和传递
typedef struct packed {
  logic clk;                     // input
  logic rst;                     // input
  logic [DATA_WIDTH-1:0] data;  // input
  logic valid;                     // input
  logic ready;                     // output
} apb_uart_out_struct_t;