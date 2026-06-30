// shift_accumulator — 25-bit right-shift-2 multi-cycle accumulator
module shift_accumulator (
    input  wire         clk, rst_n, sample_en,
    input  wire [3:0]   num_iterations,
    input  wire [15:0]  psum_i,
    input  wire         psum_valid_i,
    output reg  [24:0]  result_o,
    output reg          valid_o,
    output reg          done_o
);
    reg [24:0] accum;
    reg [3:0]  iter;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin accum<=25'd0; iter<=4'd0; valid_o<=1'b0; done_o<=1'b0; end
        else if (sample_en && psum_valid_i) begin
            if (iter==0) accum <= {psum_i + 16'd0, 9'd0};
            else         accum <= (accum >> 2) + {psum_i + 16'd0, 9'd0};
            iter <= iter + 1;
            if (iter == num_iterations-1) done_o <= 1'b1;
        end else if (done_o) begin result_o<=accum; valid_o<=1'b1; done_o<=1'b0; iter<=0; end
        else valid_o<=1'b0;
    end
endmodule
