// Interface Structure: UART_in_struct
// 将 interface 信号封装为 struct，便于采样和传递
typedef struct packed {
  logic pclk;                     // input
  logic presetn;                     // input
  logic tx;                     // output
  logic rx;                     // input
  logic [4-1:0] interrupt;  // output
} UART_in_struct_t;