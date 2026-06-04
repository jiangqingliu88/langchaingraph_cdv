// 自动生成的 Interface: UART_in
interface UART_in_interface #(
  parameter int DATA_WIDTH = 32
) (input  logic pclk,input  logic presetn,output logic tx,input  logic rx,output logic [4-1:0] interrupt
);

  // HDL 类型定义

  // 时钟块
  clocking cb @(posedge pclk);output tx;input rx;output interrupt;
  endclocking : cb

  // Modport
  modport mp (
    input  pclk,
    input  presetn,output tx,input rx,output interrupt,
    clocking cb
  );

  // 复位断言电平:  (可用于驱动逻辑)

endinterface : UART_in_interface