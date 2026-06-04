// Interface Structure: AXI_in_struct
// 将 interface 信号封装为 struct，便于采样和传递
typedef struct packed {
  logic pclk;                     // input
  logic presetn;                     // input
  logic [32-1:0] awaddr;  // output
  logic awvalid;                     // output
  logic awready;                     // input
  logic [32-1:0] wdata;  // output
  logic wvalid;                     // output
  logic wready;                     // input
  logic [32-1:0] araddr;  // output
  logic arvalid;                     // output
  logic arready;                     // input
  logic [32-1:0] rdata;  // input
  logic rvalid;                     // input
  logic rready;                     // output
} AXI_in_struct_t;