//==============================================================================
// compute_format — Decode 17 compute combinations for input_process + dcim
// Maps config_format[10:0] → processing flags for all 17 supported combos
//==============================================================================
module compute_format (
    input  wire [10:0]  cfg_fmt,        // [10]=MX [9:5]=input [4:0]=weight

    //── Decoded flags ─────────────────────────────────────────────
    output wire         input_is_int,   // INT type (no alignment needed)
    output wire         input_is_fp,    // FP type (needs alignment)
    output wire         input_is_mx,    // MX type (needs share_exp)
    output wire         input_is_mx_fp, // MX-FP (align + share_exp)
    output wire         input_is_mx_int,// MX-INT (share_exp only, no align)
    output wire         weight_is_int,
    output wire         weight_is_fp,
    output wire         weight_is_mx,
    output wire [2:0]   input_wd,       // width: 010=4 011=8 100=16 101=32
    output wire [2:0]   weight_wd,
    output wire [3:0]   num_iterations, // BOOTH4 iters: 2/4/8
    output wire         needs_align,    // input needs FP alignment
    output wire         needs_share_exp,// input needs MX share_exp addition
    output wire         output_is_fp32, // output format: 0=INT32 1=FP32
    output wire [3:0]   combo_id        // 1-17 which combination
);

    //── Extract fields ────────────────────────────────────────────
    wire       mx_en       = cfg_fmt[10];
    wire [4:0] input_prec  = cfg_fmt[9:5];
    wire [4:0] weight_prec = cfg_fmt[4:0];

    wire       in_mx   = input_prec[4];           // MX flag
    wire       in_fp   = input_prec[3];           // FP/INT flag
    wire [2:0] in_wd   = input_prec[2:0];
    wire       wt_mx   = weight_prec[4];
    wire       wt_fp   = weight_prec[3];
    wire [2:0] wt_wd   = weight_prec[2:0];

    assign input_is_int    = !in_fp && !in_mx;
    assign input_is_fp     =  in_fp && !in_mx;
    assign input_is_mx     =  in_mx;
    assign input_is_mx_fp  =  in_mx &&  in_fp;
    assign input_is_mx_int =  in_mx && !in_fp;
    assign weight_is_int   = !wt_fp && !wt_mx;
    assign weight_is_fp    =  wt_fp && !wt_mx;
    assign weight_is_mx    =  wt_mx;
    assign input_wd        = in_wd;
    assign weight_wd       = wt_wd;

    //── BOOTH4 iterations: width/2 ────────────────────────────────
    assign num_iterations = (in_wd == 3'b010) ? 4'd2 :    // 4-bit
                            (in_wd == 3'b011) ? 4'd4 :    // 8-bit
                            (in_wd == 3'b100) ? 4'd8 : 4'd4; // 16-bit

    //── Alignment needed: FP or MX-FP → yes, INT/MX-INT → no ──────
    assign needs_align = input_is_fp || input_is_mx_fp;

    //── Share EXP needed: MX type → yes ───────────────────────────
    assign needs_share_exp = input_is_mx;

    //── Output format: FP32 for all 17 combos (PSUM=INT32 optional)─
    assign output_is_fp32 = 1'b1;   // All combos output FP32 (or INT32 via config)

    //── Combo ID (1-17) ───────────────────────────────────────────
    wire [9:0] combo_key = {input_prec, weight_prec};
    assign combo_id =
        (combo_key == COMB_INT8_INT4)     ? 4'd1  :
        (combo_key == COMB_INT8_INT8)     ? 4'd2  :
        (combo_key == COMB_FP16_FP16)     ? 4'd3  :
        (combo_key == COMB_BF16_BF16)     ? 4'd4  :
        (combo_key == COMB_FP8_FP8)       ? 4'd5  :
        (combo_key == COMB_BF16_FP16)     ? 4'd6  :
        (combo_key == COMB_FP16_BF16)     ? 4'd7  :
        (combo_key == COMB_FP16_INT4)     ? 4'd8  :
        (combo_key == COMB_BF16_INT4)     ? 4'd9  :
        (combo_key == COMB_FP16_INT8)     ? 4'd10 :
        (combo_key == COMB_BF16_INT8)     ? 4'd11 :
        (combo_key == COMB_INT8_FP16)     ? 4'd12 :
        (combo_key == COMB_INT8_BF16)     ? 4'd13 :
        (combo_key == COMB_MXINT8_MXINT8) ? 4'd14 :
        (combo_key == COMB_FP16_MXINT8)   ? 4'd15 :
        (combo_key == COMB_BF16_MXINT8)   ? 4'd16 :
        (combo_key == COMB_FP8_MXINT8)    ? 4'd17 : 4'd0;

endmodule
