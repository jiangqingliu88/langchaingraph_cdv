// Interface Structure: UART_out_struct
// 将 interface 信号封装为 struct，便于采样和传递
typedef struct packed {
  logic pclk;                     // input
  logic presetn;                     // input
  logic tx;                     // output
  logic rx;                     // input
} UART_out_struct_t;