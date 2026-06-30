// adder_tree — 64×11-bit PSUM → 16-bit accumulated sum
module adder_tree (
    input  wire         clk, rst_n, sample_en,
    input  wire [703:0] data_psum_i,   // 64×11-bit
    input  wire [63:0]  mask_en,
    output reg  [15:0]  sum_o,
    output reg          valid_o
);
    wire [63:0][10:0] col;
    genvar i;
    generate for (i=0; i<64; i=i+1) assign col[i] = data_psum_i[i*11 +: 11]; endgenerate
    wire [16:0] total = {6'd0, col[0]} + {6'd0, col[1]} + {6'd0, col[2]} + {6'd0, col[3]};
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin sum_o<=16'd0; valid_o<=1'b0; end
        else if (sample_en) begin sum_o<=total[15:0]; valid_o<=1'b1; end
        else valid_o<=1'b0;
    end
endmodule
