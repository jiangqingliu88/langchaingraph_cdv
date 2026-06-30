//==============================================================================
// input_process — Supports all 17 compute combinations
//
// Processing per input type:
//   INT:     bypass → BOOTH4 encode directly
//   FP/BF:   find max EXP among elements → shift mantissa → BOOTH4
//   MX-INT:  bypass mantissa, EXP = in_exp + share_exp
//   MX-FP:   align EXP + shift + add share_exp → BOOTH4
//
// After alignment, all mantissas are treated as INT for BOOTH4 MAC.
//==============================================================================
module input_process #(
    parameter NUM_CH = 32
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         sample_en,
    input  wire [2:0]   iter,
    input  wire [3:0]   num_iterations,
    input  wire [4:0]   input_prec,     // [4]=MX [3]=FP/INT [2:0]=width
    input  wire [511:0] i_data,
    input  wire [8:0]   exp,
    input  wire [7:0]   share_exp,
    input  wire         mx_mode,
    input  wire [63:0]  mask_en,
    output reg  [31:0]  neg_o,
    output reg  [31:0]  two_o,
    output reg  [31:0]  zero_o,
    output reg  [3:0]   sign_o,
    output reg  [8:0]   exp_o,
    output reg  [511:0] manti_o
);

    //── Format decode ─────────────────────────────────────────────
    wire       in_is_fp     = input_prec[3] && !input_prec[4];
    wire       in_is_mx     = input_prec[4];
    wire       in_is_mx_fp  = input_prec[4] && input_prec[3];
    wire       needs_align  = in_is_fp || in_is_mx_fp;
    wire [2:0] in_wd        = input_prec[2:0];

    //── FP alignment: find max EXP among elements ─────────────────
    reg [511:0] aligned_data;
    reg [8:0]   aligned_exp;
    reg         align_done;
    integer ei;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            aligned_data <= 512'd0;
            aligned_exp  <= 9'd0;
            align_done   <= 1'b0;
        end else if (sample_en && needs_align) begin
            if (in_wd == 3'b100) begin : fp16_align
                // FP16/BF16: 32 elements × 16b per 512b
                // Format: [15]=sign [14:10]=exp [9:0]=mantissa
                reg [4:0] max_e; max_e = 5'd0;
                for (ei = 0; ei < 32; ei = ei + 1)
                    if (i_data[ei*16+14 -: 5] > max_e)
                        max_e = i_data[ei*16+14 -: 5];
                aligned_exp <= {4'd0, max_e};
                aligned_data <= i_data;  // mantissa shift in DCIM stage
            end else begin : fp8_align
                // FP8: 64 elements × 8b per 512b
                // Format: [7]=sign [6:2]=exp [1:0]=mantissa
                reg [4:0] max_e; max_e = 5'd0;
                for (ei = 0; ei < 64; ei = ei + 1)
                    if (i_data[ei*8+6 -: 5] > max_e)
                        max_e = i_data[ei*8+6 -: 5];
                aligned_exp <= {4'd0, max_e};
                aligned_data <= i_data;
            end
            align_done <= 1'b1;
        end else begin
            align_done <= 1'b0;
        end
    end

    //── EXP routing per combination ───────────────────────────────
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            exp_o <= 9'd0;
        end else if (sample_en) begin
            if (in_is_mx_fp)
                exp_o <= aligned_exp + {1'b0, share_exp};    // MX-FP: align + share
            else if (in_is_mx && !input_prec[3])               // MX-INT
                exp_o <= exp + {1'b0, share_exp};
            else if (in_is_fp)
                exp_o <= aligned_exp;                          // FP: aligned only
            else
                exp_o <= 9'd0;                                 // INT: no exp
        end
    end

    //── Mantissa routing ──────────────────────────────────────────
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            manti_o <= 512'd0;
        end else if (sample_en) begin
            manti_o <= needs_align ? aligned_data : i_data;
        end
    end

    //── BOOTH4-RADIX Encode (all types use INT mantissa after alignment) ──
    integer ch;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            neg_o  <= 32'd0; two_o  <= 32'd0; zero_o <= 32'hFFFF_FFFF;
            sign_o <= 4'd0;
        end else if (sample_en) begin
            sign_o <= 4'd0;
            for (ch = 0; ch < NUM_CH; ch = ch + 1) begin : booth_ch
                reg [2:0] triple;
                // iter=0: bits[1:0,-1=0]; iter=N: bits[2N+1:2N-1]
                if (iter == 3'd0)
                    triple = {manti_o[ch*16+1], manti_o[ch*16+0], 1'b0};
                else
                    triple = manti_o[ch*16 + iter*2 +: 3];

                case (triple)
                    3'b000, 3'b111:  {neg_o[ch],two_o[ch],zero_o[ch]} = 3'b001;
                    3'b001, 3'b010:  {neg_o[ch],two_o[ch],zero_o[ch]} = 3'b000;
                    3'b011:          {neg_o[ch],two_o[ch],zero_o[ch]} = 3'b010;
                    3'b100:          {neg_o[ch],two_o[ch],zero_o[ch]} = 3'b110;
                    3'b101, 3'b110:  {neg_o[ch],two_o[ch],zero_o[ch]} = 3'b100;
                    default:         {neg_o[ch],two_o[ch],zero_o[ch]} = 3'b001;
                endcase
            end
        end
    end

endmodule
