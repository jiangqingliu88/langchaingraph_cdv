// exponent_mux — route dcim exponent to 144-bit output
module exponent_mux (
    input  wire         clk, rst_n, sample_en,
    input  wire [287:0] dcim_exp_i,
    input  wire [4:0]   weight_prec,
    input  wire [63:0]  mask_en,
    output reg  [143:0] exp_o
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) exp_o <= 144'd0;
        else if (sample_en) exp_o <= dcim_exp_i[143:0];
    end
endmodule
