// mantissa_mux — route accum result to 592-bit mantissa output
module mantissa_mux (
    input  wire         clk, rst_n, sample_en,
    input  wire [24:0]  accum_result_i,
    input  wire         accum_valid_i,
    input  wire [4:0]   weight_prec,
    input  wire [63:0]  mask_en,
    output reg  [591:0] manti_o
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) manti_o <= 592'd0;
        else if (sample_en && accum_valid_i) manti_o <= {592{1'b0}} | accum_result_i;
    end
endmodule
