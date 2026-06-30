//==============================================================================
// TMU — Weight EXP handler (Temporary Memory Unit for CIM weight)
// Handles 6 scenarios for weight EXP processing:
//   Scenario 1 (INT×INT):  bypass, no EXP
//   Scenario 2 (INT×FP):   FP weight → remove bias, 2's complement, output 9-bit EXP
//   Scenario 3 (FP×INT):   INT weight → bypass, CIMM outputs 9-bit EXP
//   Scenario 4 (FP×FP):    FP weight → remove bias, 2's complement, CIMM EXP相加
//   Scenario 5 (MX×MX):    MX_INT weight → bypass int, CIMM EXP相加
//   Scenario 6 (FP×MX):    MX_INT weight → bypass int, CIMM EXP相加
//==============================================================================
module tmu (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         sample_en,
    input  wire [4:0]   weight_prec,    // [4]=MX [3]=FP/INT [2:0]=width
    input  wire [7:0]   weight_exp_i,   // raw weight EXP from SRAM exp_row
    output reg  [8:0]   weight_exp_o,   // processed EXP (9-bit signed)
    output reg          exp_valid_o
);

    //── Weight type decode ────────────────────────────────────────
    wire wt_is_fp  = weight_prec[3] && !weight_prec[4];   // FP16/BF16/FP8
    wire wt_is_mx  = weight_prec[4];
    wire wt_is_int = !weight_prec[3] && !weight_prec[4];

    // FP16: bias=15, BF16: bias=127, FP8E5M2: bias=15, FP8E4M3: bias=7
    wire [7:0] fp_bias = (weight_prec[2:0] == 3'b100 && weight_prec[3]) ? 8'd15 :   // FP16
                         (weight_prec[2:0] == 3'b100 && !weight_prec[3])? 8'd127:    // BF16 (type=BF)
                         (weight_prec[2:0] == 3'b011 && !weight_prec[4])? 8'd7 :     // FP8E4M3
                         (weight_prec[2:0] == 3'b011 && weight_prec[3]) ? 8'd15:     // FP8E5M2
                         8'd15;  // default FP16 bias

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            weight_exp_o <= 9'd0;
            exp_valid_o  <= 1'b0;
        end else if (sample_en) begin
            if (wt_is_fp) begin
                // FP weight: remove bias → 2's complement for signed EXP comparison
                // EXP_signed = {1'b0, weight_exp} - bias → signed 9-bit
                weight_exp_o <= {1'b0, weight_exp_i} - {1'b0, fp_bias};
            end else if (wt_is_mx) begin
                // MX-INT: pass through (shared EXP handled separately)
                weight_exp_o <= {1'b0, weight_exp_i};
            end else begin
                // INT weight: bypass (no EXP from weight side)
                weight_exp_o <= 9'd0;
            end
            exp_valid_o <= 1'b1;
        end else begin
            exp_valid_o <= 1'b0;
        end
    end

endmodule
