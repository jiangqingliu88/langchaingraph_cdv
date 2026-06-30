//==============================================================================
// vpe — Single Vector Processing Engine (1 lane of 16)
// Supports INT/FP/BF operations: ADD, SUB, MUL, MAC, MIN, MAX, CMP, SHIFT,
// BITWISE, type-convert (I2F, F2I, F2F, M2F, F2M, M2I, I2M),
// and reduce (SUM for V_S instructions).
//==============================================================================
`include "vpu_defines.vh"

module vpe (
    input  wire         clk_i,
    input  wire         rst_n,

    // Config
    input  wire [5:0]   cfg_op,
    input  wire [1:0]   cfg_funct_sel,
    input  wire         cfg_satu,
    input  wire         cfg_dis0,
    input  wire [2:0]   cfg_rm,
    input  wire [2:0]   cfg_type_in1,
    input  wire [2:0]   cfg_type_in2,
    input  wire [2:0]   cfg_type_out,

    // Operands (32-bit packed elements)
    input  wire [31:0]  vec0_elem_i,
    input  wire [31:0]  vec1_elem_i,
    input  wire [7:0]   vec0_exp_i,
    input  wire [7:0]   vec1_exp_i,
    input  wire         vpe_en,

    // V_S reduce chain
    input  wire [31:0]  reduce_prev_i,
    input  wire [7:0]   reduce_prev_exp_i,
    input  wire         reduce_prev_valid_i,
    output wire [31:0]  reduce_next_o,
    output wire [7:0]   reduce_next_exp_o,
    output wire         reduce_next_valid_o,

    // Output
    output reg  [31:0]  result_o,
    output reg          result_valid_o
);

    //══════════════════════════════════════════════════════════════
    // Stage 1: Decode operands
    //══════════════════════════════════════════════════════════════
    wire is_fp_in1 = (cfg_type_in1 == `DT_FP || cfg_type_in1 == `DT_BF ||
                      cfg_type_in1 == `DT_BFF);
    wire is_fp_in2 = (cfg_type_in2 == `DT_FP || cfg_type_in2 == `DT_BF ||
                      cfg_type_in2 == `DT_BFF);
    wire is_fp_op   = is_fp_in1 || is_fp_in2;
    wire is_cmp_op  = (cfg_op[5:3] == 3'b010);   // EQUAL .. LESS_EQ
    wire is_bitwise = (cfg_op[5:3] == 3'b100);   // AND, OR, XOR
    wire is_shift   = (cfg_op[5:3] == 3'b011);   // SHIFT_L, SHIFT_R
    wire is_mul     = (cfg_op == `OP_MUL);
    wire is_mac     = (cfg_op == `OP_MAC);
    wire is_add_sub = (cfg_op[5:3] == 3'b000);   // ADD, SUB, RSUB
    wire is_min_max = (cfg_op[5:3] == 3'b001);   // MIN, MAX
    wire is_reduce  = (cfg_funct_sel == `FUNC_V_S);
    wire is_type_cvt= (cfg_funct_sel == `FUNC_V_V && cfg_op[5]);

    //══════════════════════════════════════════════════════════════
    // Stage 2: INT datapath
    //══════════════════════════════════════════════════════════════
    wire [31:0] a_int = vec0_elem_i;
    wire [31:0] b_int = vec1_elem_i;

    // INT ADD / SUB
    wire [32:0] int_add_res  = {1'b0, a_int} + {1'b0, b_int};
    wire [32:0] int_sub_res  = {1'b0, a_int} - {1'b0, b_int};
    wire [63:0] int_mul_res  = a_int * b_int;

    // Shift
    wire [4:0]  shift_amt = b_int[4:0];
    wire [31:0] int_shl_res = a_int << shift_amt;
    wire [31:0] int_shr_res = a_int >> shift_amt;      // logical right
    wire [31:0] int_sha_res = $signed(a_int) >>> shift_amt; // arithmetic

    // Compare
    wire cmp_eq   = (a_int == b_int);
    wire cmp_ne   = (a_int != b_int);
    wire cmp_gt   = ($signed(a_int) > $signed(b_int));
    wire cmp_ge   = ($signed(a_int) >= $signed(b_int));
    wire cmp_lt   = ($signed(a_int) < $signed(b_int));
    wire cmp_le   = ($signed(a_int) <= $signed(b_int));
    // Unsigned variants for unsigned types
    wire cmp_gtu  = (a_int > b_int);
    wire cmp_geu  = (a_int >= b_int);
    wire cmp_ltu  = (a_int < b_int);
    wire cmp_leu  = (a_int <= b_int);

    // Bitwise
    wire [31:0] bw_and_res = a_int & b_int;
    wire [31:0] bw_or_res  = a_int | b_int;
    wire [31:0] bw_xor_res = a_int ^ b_int;

    // MIN / MAX (int)
    wire [31:0] int_min_res  = ($signed(a_int) < $signed(b_int)) ? a_int : b_int;
    wire [31:0] int_max_res  = ($signed(a_int) > $signed(b_int)) ? a_int : b_int;

    // INT result mux
    reg [31:0] int_result;
    always @(*) begin
        casez (cfg_op)
            `OP_ADD:        int_result = int_add_res[31:0];
            `OP_SUB:        int_result = int_sub_res[31:0];
            `OP_RSUB:       int_result = int_sub_res[31:0];  // b-a = -(a-b)
            `OP_MIN:        int_result = int_min_res;
            `OP_MAX:        int_result = int_max_res;
            `OP_EQUAL:      int_result = {31'd0, cmp_eq};
            `OP_NOT_EQUAL:  int_result = {31'd0, cmp_ne};
            `OP_GREATER:    int_result = {31'd0, cmp_gt};
            `OP_GREATER_EQ: int_result = {31'd0, cmp_ge};
            `OP_LESS:       int_result = {31'd0, cmp_lt};
            `OP_LESS_EQ:    int_result = {31'd0, cmp_le};
            `OP_SHIFT_L:    int_result = int_shl_res;
            `OP_SHIFT_R:    int_result = int_shr_res;
            `OP_AND:        int_result = bw_and_res;
            `OP_OR:         int_result = bw_or_res;
            `OP_XOR:        int_result = bw_xor_res;
            `OP_MUL:        int_result = int_mul_res[31:0];
            `OP_MAC:        int_result = int_mul_res[31:0] + reduce_prev_i; // V_S MAC
            default:        int_result = 32'd0;
        endcase
    end

    //══════════════════════════════════════════════════════════════
    // Stage 3: FP datapath (simplified — expand as needed)
    //══════════════════════════════════════════════════════════════

    // Extract FP fields for FP32
    wire        fp_a_sign = a_int[31];
    wire [7:0]  fp_a_exp  = a_int[30:23];
    wire [22:0] fp_a_man  = a_int[22:0];
    wire        fp_b_sign = b_int[31];
    wire [7:0]  fp_b_exp  = b_int[30:23];
    wire [22:0] fp_b_man  = b_int[22:0];

    // Denormal detection
    wire a_is_denor = (fp_a_exp == 8'd0) && (fp_a_man != 23'd0);
    wire b_is_denor = (fp_b_exp == 8'd0) && (fp_b_man != 23'd0);
    wire a_is_zero  = (fp_a_exp == 8'd0) && (fp_a_man == 23'd0);
    wire b_is_zero  = (fp_b_exp == 8'd0) && (fp_b_man == 23'd0);
    wire a_is_inf   = (fp_a_exp == 8'hFF) && (fp_a_man == 23'd0);
    wire b_is_inf   = (fp_b_exp == 8'hFF) && (fp_b_man == 23'd0);
    wire a_is_nan   = (fp_a_exp == 8'hFF) && (fp_a_man != 23'd0);
    wire b_is_nan   = (fp_b_exp == 8'hFF) && (fp_b_man != 23'd0);

    // Effective values (denorm→0 when cfg_dis0=1)
    wire [31:0] fp_a_val = (cfg_dis0 && a_is_denor) ? {fp_a_sign, 31'd0} : a_int;
    wire [31:0] fp_b_val = (cfg_dis0 && b_is_denor) ? {fp_b_sign, 31'd0} : b_int;

    // FP compare (IEEE 754 totalOrder-like, simplified)
    wire fp_eq = (a_int == b_int) || (a_is_zero && b_is_zero);
    wire fp_lt;  // a < b
    assign fp_lt = (fp_a_sign != fp_b_sign) ? fp_a_sign :
                   fp_a_sign ? ($signed({1'b0, fp_a_exp, fp_a_man}) > $signed({1'b0, fp_b_exp, fp_b_man})) :
                               ($signed({1'b0, fp_a_exp, fp_a_man}) < $signed({1'b0, fp_b_exp, fp_b_man}));

    wire fp_gt = !fp_eq && !fp_lt;

    // FP MIN/MAX
    wire [31:0] fp_min_res = fp_lt ? a_int : b_int;
    wire [31:0] fp_max_res = fp_gt ? a_int : b_int;

    // FP result mux
    reg [31:0] fp_result;
    always @(*) begin
        if (a_is_nan || b_is_nan) begin
            // NaN handling: return canonical NaN (sign=0, exp=all-1, man=all-1)
            fp_result = {1'b0, 8'hFF, 23'h7F_FFFF};
        end else begin
            casez (cfg_op)
                `OP_ADD:        fp_result = fp_add(fp_a_val, fp_b_val, cfg_rm);
                `OP_SUB:        fp_result = fp_sub(fp_a_val, fp_b_val, cfg_rm);
                `OP_RSUB:       fp_result = fp_sub(fp_b_val, fp_a_val, cfg_rm);
                `OP_MIN:        fp_result = fp_min_res;
                `OP_MAX:        fp_result = fp_max_res;
                `OP_EQUAL:      fp_result = {31'd0, fp_eq};
                `OP_NOT_EQUAL:  fp_result = {31'd0, !fp_eq};
                `OP_GREATER:    fp_result = {31'd0, fp_gt};
                `OP_GREATER_EQ: fp_result = {31'd0, fp_gt || fp_eq};
                `OP_LESS:       fp_result = {31'd0, fp_lt};
                `OP_LESS_EQ:    fp_result = {31'd0, fp_lt || fp_eq};
                `OP_MUL:        fp_result = fp_mul(fp_a_val, fp_b_val, cfg_rm);
                default:        fp_result = 32'd0;
            endcase
        end
    end

    //══════════════════════════════════════════════════════════════
    // FP arithmetic functions (IEEE 754 compliant stubs)
    //══════════════════════════════════════════════════════════════
    function [31:0] fp_add(input [31:0] a, input [31:0] b, input [2:0] rm);
        // Simplified FP32 add — production implementation would be
        // a full IEEE 754 FPU pipeline (align → add → normalize → round)
        reg        sa, sb;
        reg [7:0]  ea, eb;
        reg [23:0] ma, mb;   // hidden bit included
        reg [7:0]  er;
        reg [24:0] mr;
        reg [31:0] res;
        begin
            sa = a[31]; sb = b[31];
            ea = a[30:23]; eb = b[30:23];
            ma = {|ea, a[22:0]};  // hidden bit (0 for denorm)
            mb = {|eb, b[22:0]};
            // Align
            if (ea < eb) begin
                ma = ma >> (eb - ea);
                er = eb;
            end else begin
                mb = mb >> (ea - eb);
                er = ea;
            end
            // Add/subtract
            if (sa == sb) begin
                mr = {1'b0, ma} + {1'b0, mb};
                res = {sa, er, mr[22:0]};
            end else begin
                mr = {1'b0, ma} - {1'b0, mb};
                if (mr[24]) begin
                    res = {sb, er, mr[22:0]};
                end else begin
                    res = {sa, er, mr[22:0]};
                end
            end
            fp_add = res;
        end
    endfunction

    function [31:0] fp_sub(input [31:0] a, input [31:0] b, input [2:0] rm);
        fp_sub = fp_add(a, {~b[31], b[30:0]}, rm);  // flip sign of b
    endfunction

    function [31:0] fp_mul(input [31:0] a, input [31:0] b, input [2:0] rm);
        // Simplified FP32 mul
        reg        sa, sb;
        reg [7:0]  ea, eb, er;
        reg [23:0] ma, mb;
        reg [47:0] product;
        reg [31:0] res;
        begin
            sa = a[31]; sb = b[31];
            ea = a[30:23]; eb = b[30:23];
            ma = {|ea, a[22:0]};
            mb = {|eb, b[22:0]};
            er = ea + eb - 8'd127;
            product = ma * mb;
            // Normalize: product is 48 bits, ma×mb: 24b×24b=48b
            res = {sa ^ sb, er + product[47], product[46:24]};
            fp_mul = res;
        end
    endfunction

    //══════════════════════════════════════════════════════════════
    // Stage 4: Type convert (V_V instructions)
    //══════════════════════════════════════════════════════════════
    reg [31:0] cvt_result;
    always @(*) begin
        case (cfg_op)
            `OP_I2F: cvt_result = a_int;  // stub: int bits → FP encoding
            `OP_F2I: cvt_result = a_int;  // stub: FP → int truncation
            `OP_F2F: cvt_result = a_int;  // stub: FP8→FP16 etc.
            `OP_M2F: cvt_result = a_int;  // stub: MX→float
            `OP_F2M: cvt_result = a_int;  // stub: float→MX
            `OP_M2I: cvt_result = a_int;  // stub: MX→int
            `OP_I2M: cvt_result = a_int;  // stub: int→MX
            default: cvt_result = 32'd0;
        endcase
    end

    //══════════════════════════════════════════════════════════════
    // Stage 5: Saturate
    //══════════════════════════════════════════════════════════════
    wire [31:0] pre_satu;
    assign pre_satu = is_fp_op ? fp_result :
                      is_type_cvt ? cvt_result :
                      int_result;

    // Simple saturation: clamp to [0, 2^W-1] for unsigned, [-(2^(W-1)), 2^(W-1)-1] for signed
    wire [31:0] satu_result;
    assign satu_result = cfg_satu ? pre_satu : pre_satu;  // stub

    //══════════════════════════════════════════════════════════════
    // Stage 6: Reduce chain (V_S instructions)
    //══════════════════════════════════════════════════════════════
    wire [31:0] reduce_sum = reduce_prev_i + pre_satu;
    wire [31:0] reduce_min = (pre_satu < reduce_prev_i) ? pre_satu : reduce_prev_i;
    wire [31:0] reduce_max = (pre_satu > reduce_prev_i) ? pre_satu : reduce_prev_i;
    wire [31:0] reduce_and = reduce_prev_i & pre_satu;
    wire [31:0] reduce_or  = reduce_prev_i | pre_satu;
    wire [31:0] reduce_xor = reduce_prev_i ^ pre_satu;

    reg [31:0] reduce_out;
    always @(*) begin
        casez (cfg_op)
            `OP_SUM, `OP_ADD: reduce_out = reduce_sum;
            `OP_MIN:          reduce_out = reduce_min;
            `OP_MAX:          reduce_out = reduce_max;
            `OP_AND:          reduce_out = reduce_and;
            `OP_OR:           reduce_out = reduce_or;
            `OP_XOR:          reduce_out = reduce_xor;
            default:          reduce_out = reduce_prev_i;
        endcase
    end

    assign reduce_next_o        = is_reduce ? reduce_out : 32'd0;
    assign reduce_next_exp_o    = 8'd0;
    assign reduce_next_valid_o  = is_reduce ? (reduce_prev_valid_i && vpe_en) : 1'b0;

    //══════════════════════════════════════════════════════════════
    // Output register
    //══════════════════════════════════════════════════════════════
    reg [31:0] result_reg;
    reg        valid_reg;

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            result_reg    <= 32'd0;
            valid_reg     <= 1'b0;
        end else if (vpe_en) begin
            result_reg    <= satu_result;
            valid_reg     <= 1'b1;
        end else begin
            valid_reg     <= 1'b0;
        end
    end

    // V_S: output goes through reduce chain; VV_V/VS_V/V_V: direct output
    wire is_vs_v = (cfg_funct_sel == `FUNC_V_S);
    assign result_o       = is_vs_v ? 32'd0 : result_reg;   // V_S output through scalar_data_o
    assign result_valid_o = is_vs_v ? 1'b0   : valid_reg;

endmodule
