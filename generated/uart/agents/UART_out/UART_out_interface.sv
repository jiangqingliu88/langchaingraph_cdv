// 自动生成的 Interface: UART_out
interface UART_out_interface #(
  parameter int DATA_WIDTH = 32
) (input  logic pclk,input  logic presetn,output logic tx,input  logic rx
);

  // HDL 类型定义

  // 时钟块
  clocking cb @(posedge pclk);output tx;input rx;
  endclocking : cb

  // Modport
  modport mp (
    input  pclk,
    input  presetn,output tx,input rx,
    clocking cb
  );

  // 复位断言电平:  (可用于驱动逻辑)

endinterface : UART_out_interface