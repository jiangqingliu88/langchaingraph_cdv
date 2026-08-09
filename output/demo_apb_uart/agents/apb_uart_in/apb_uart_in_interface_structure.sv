// Interface Structure: apb_uart_in_struct
// 将 interface 信号封装为 struct，便于采样和传递
typedef struct packed {
  logic clk;                     // input
  logic rst;                     // input
  logic [DATA_WIDTH-1:0] data;  // output
  logic valid;                     // output
  logic ready;                     // input
} apb_uart_in_struct_t;