// 自动生成的 Interface: AXI_in
interface AXI_in_interface #(
  parameter int DATA_WIDTH = 32
) (input  logic pclk,input  logic presetn,output logic [32-1:0] awaddr,output logic awvalid,input  logic awready,output logic [32-1:0] wdata,output logic wvalid,input  logic wready,output logic [32-1:0] araddr,output logic arvalid,input  logic arready,input  logic [32-1:0] rdata,input  logic rvalid,output logic rready
);

  // HDL 类型定义

  // 时钟块
  clocking cb @(posedge pclk);output awaddr;output awvalid;input awready;output wdata;output wvalid;input wready;output araddr;output arvalid;input arready;input rdata;input rvalid;output rready;
  endclocking : cb

  // Modport
  modport mp (
    input  pclk,
    input  presetn,output awaddr,output awvalid,input awready,output wdata,output wvalid,input wready,output araddr,output arvalid,input arready,input rdata,input rvalid,output rready,
    clocking cb
  );

  // 复位断言电平:  (可用于驱动逻辑)

endinterface : AXI_in_interface