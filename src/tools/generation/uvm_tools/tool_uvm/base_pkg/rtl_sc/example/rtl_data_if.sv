interface rtl_data_if #(int DW = 256) (input logic clk, input logic rst_n);
    logic             valid;
    logic [63:0]      addr;
    logic [DW-1:0]    data;
    logic [15:0]      byte_len;
endinterface
