// 自动生成的 Interface: apb_uart_out
interface apb_uart_out_interface #(
  parameter int DATA_WIDTH = 32
) (input  logic clk,input  logic rst,input  logic [DATA_WIDTH-1:0] data,input  logic valid,output logic ready
);

  // HDL 类型定义

  // 时钟块
  clocking cb @(posedge clk);input data;input valid;output ready;
  endclocking : cb

  // Modport
  modport mp (
    input  clk,
    input  rst,input data,input valid,output ready,
    clocking cb
  );

  // 复位断言电平:  (可用于驱动逻辑)

endinterface : apb_uart_out_interface