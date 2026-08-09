// 自动生成的 Interface: apb_uart_in
interface apb_uart_in_interface #(
  parameter int DATA_WIDTH = 32
) (input  logic clk,input  logic rst,output logic [DATA_WIDTH-1:0] data,output logic valid,input  logic ready
);

  // HDL 类型定义

  // 时钟块
  clocking cb @(posedge clk);output data;output valid;input ready;
  endclocking : cb

  // Modport
  modport mp (
    input  clk,
    input  rst,output data,output valid,input ready,
    clocking cb
  );

  // 复位断言电平:  (可用于驱动逻辑)

endinterface : apb_uart_in_interface