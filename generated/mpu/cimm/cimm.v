//==============================================================================
// CIMM — CIM Macro Top-Level (real interface alignment)
// 64 channels, SRAM 256b×16p×33r, BOOTH4 via dcim_ip_bm_core
// Sub-modules: controller, input_process, dcim_ip_bm_core, post_process,
//              shift_accumulator, trans_int37, adder_tree, mantissa_mux,
//              exponent_mux, cbist_top, lcnter, lcomp, mcnter, mcomp
//==============================================================================
module cimm (
    input  wire                storage_clk,        // 存储域时钟 500MHz
    input  wire                compute_clk,        // 计算域时钟 500MHz
    input  wire                allon_clk,          // 全开时钟 (DFT)
    input  wire                rst_n,              // 异步复位, 低有效

    //── Storage Interface ────────────────────────────────────────
    input  wire                wen,                // 写使能
    input  wire                ren_global,         // 全局读使能
    input  wire                ren_local,          // 本地读使能 (设置PAGE)
    input  wire                cen,                // 计算使能
    input  wire [10:0]         cfg_fmt,            // [10]=MX [9:5]=输入精度 [4:0]=权重精度
    input  wire [63:0]         mask_en,            // 64通道使能MASK
    input  wire [9:0]          addr,               // 地址 {page[3:0], row[5:0]}
    input  wire [255:0]        mem_d,              // 写数据
    input  wire [511:0]        i_data,             // 输入Activation (16 elements × 32b)
    input  wire [8:0]          exp,                // 输入指数 (对齐后)
    input  wire [7:0]          share_exp,          // MX共享指数

    //── Output ───────────────────────────────────────────────────
    output wire [255:0]        mem_q,              // 读数据
    output wire [591:0]        o_manti,            // 输出尾数
    output wire [143:0]        o_exp,              // 输出指数
    output wire                o_data_flag,        // 输出有效标志

    //── Debug ────────────────────────────────────────────────────
    input  wire [26:0]         creg_dcim_ema,      // EMA debug register

    //── DFT / BIST ───────────────────────────────────────────────
    input  wire                dft_bist_mode,      // BIST模式
    input  wire                dft_bist_start,     // BIST开始
    input  wire                dft_mbist_en,       // MBIST使能
    input  wire                dft_lbist_en,       // LBIST使能
    input  wire                dft_alg_sel,        // 算法选择 0:zero-one 1:checkerboard
    output wire                dft_ram_cen,        // RAM片选 (低有效)
    output wire                dft_ram_wen,        // RAM写使能 (低有效)
    output wire [8:0]          dft_ram_addr,       // RAM地址
    input  wire [511:0]        dft_ram_q,          // RAM读数据
    output wire                dft_alg_end,        // BIST算法结束
    output wire                dft_atpg_end,       // ATPG结束
    output wire                dft_lcomp_go,       // LBIST结果
    output wire                dft_mcomp_go        // MBIST结果
);

    //══════════════════════════════════════════════════════════════
    // Precision decode
    //══════════════════════════════════════════════════════════════
    wire [4:0] weight_prec = cfg_fmt[4:0];
    wire [4:0] input_prec  = cfg_fmt[9:5];
    wire       mx_mode     = cfg_fmt[10];

    wire [3:0] num_iterations = (input_prec[2:0] == 3'b010) ? 4'd2  :
                                (input_prec[2:0] == 3'b011) ? 4'd4  :
                                (input_prec[2:0] == 3'b100) ? 4'd8  : 4'd4;

    //══════════════════════════════════════════════════════════════
    // Controller — FSM: Input Sample → DCIM Sample → Post → Format
    //══════════════════════════════════════════════════════════════
    wire        ctrl_input_sample;
    wire        ctrl_dcim_sample;
    wire        ctrl_post_sample;
    wire        ctrl_format_sample;
    wire [2:0]  ctrl_iter;

    controller u_controller (
        .clk            (compute_clk),
        .rst_n          (rst_n),
        .cen            (cen),
        .num_iterations (num_iterations),
        .input_sample_o (ctrl_input_sample),
        .dcim_sample_o  (ctrl_dcim_sample),
        .post_sample_o  (ctrl_post_sample),
        .format_sample_o(ctrl_format_sample),
        .iter_o         (ctrl_iter)
    );

    //══════════════════════════════════════════════════════════════
    // Input Process — BOOTH4-RADIX encode + mantissa/exp routing
    //══════════════════════════════════════════════════════════════
    wire [31:0]  ip_neg, ip_two, ip_zero;
    wire [3:0]   ip_sign;
    wire [8:0]   ip_exp;
    wire [511:0] ip_manti;

    input_process u_input_process (
        .clk            (compute_clk),
        .rst_n          (rst_n),
        .sample_en      (ctrl_input_sample),
        .iter           (ctrl_iter),
        .num_iterations (num_iterations),
        .input_prec     (input_prec),
        .i_data         (i_data),
        .exp            (exp),
        .share_exp      (share_exp),
        .mx_mode        (mx_mode),
        .mask_en        (mask_en),
        .neg_o          (ip_neg),
        .two_o          (ip_two),
        .zero_o         (ip_zero),
        .sign_o         (ip_sign),
        .exp_o          (ip_exp),
        .manti_o        (ip_manti)
    );

    //══════════════════════════════════════════════════════════════
    // DCIM IP Core — SRAM + BOOTH4 MAC array
    //══════════════════════════════════════════════════════════════
    wire [287:0]  dcim_o_exp;      // 9*32 = 288-bit
    wire [8:0]    dcim_i_expdrv;
    wire [3:0]    dcim_signdrv;
    wire [31:0]   dcim_negdrv, dcim_twodrv, dcim_zerodrv;
    wire [703:0]  dcim_data_psum;  // 11*64 = 704-bit

    dcim_ip_bm_core u_dcim_core (
        .STORAGE_CLK (storage_clk),
        .MIX_CLK     (compute_clk),
        .WEN         (wen),
        .REN_GLOBAL  (ren_global),
        .REN_LOCAL   (ren_local),
        .ADDR        (addr),
        .I_EXP       (ip_exp),
        .O_EXP       (dcim_o_exp),
        .MASK        (mask_en),
        .D           (mem_d),
        .Q           (mem_q),
        .SIGN        (ip_sign),
        .NEG         (ip_neg),
        .TWO         (ip_two),
        .ZERO        (ip_zero),
        .I_EXPDRV    (dcim_i_expdrv),
        .SIGNDRV     (dcim_signdrv),
        .NEGDRV      (dcim_negdrv),
        .TWODRV      (dcim_twodrv),
        .ZERODRV     (dcim_zerodrv),
        .DATA_PSUM   (dcim_data_psum)
    );

    //══════════════════════════════════════════════════════════════
    // Adder Tree — 64×11-bit PSUM → multi-column accumulation
    //══════════════════════════════════════════════════════════════
    wire [15:0]  atree_sum;
    wire         atree_valid;

    adder_tree u_adder_tree (
        .clk          (compute_clk),
        .rst_n        (rst_n),
        .sample_en    (ctrl_dcim_sample),
        .data_psum_i  (dcim_data_psum),   // 64×11-bit
        .mask_en      (mask_en),
        .sum_o        (atree_sum),
        .valid_o      (atree_valid)
    );

    //══════════════════════════════════════════════════════════════
    // Shift Accumulator — 25-bit right-shift-2 accumulator
    //══════════════════════════════════════════════════════════════
    wire [24:0]  saccum_result;
    wire         saccum_valid;
    wire         saccum_done;

    shift_accumulator u_shift_accum (
        .clk            (compute_clk),
        .rst_n          (rst_n),
        .sample_en      (ctrl_dcim_sample),
        .num_iterations (num_iterations),
        .psum_i         (atree_sum),
        .psum_valid_i   (atree_valid),
        .result_o       (saccum_result),
        .valid_o        (saccum_valid),
        .done_o         (saccum_done)
    );

    //══════════════════════════════════════════════════════════════
    // TMU — Weight EXP handler (6 scenarios: remove bias, 2's comp)
    //══════════════════════════════════════════════════════════════
    wire [8:0]  tmu_exp;
    wire        tmu_exp_valid;
    wire [4:0]  weight_prec = cfg_fmt[4:0];

    tmu u_tmu (
        .clk           (compute_clk),
        .rst_n         (rst_n),
        .sample_en     (ctrl_dcim_sample),
        .weight_prec   (weight_prec),
        .weight_exp_i  (dcim_o_exp[7:0]),  // raw weight EXP from SRAM exp_row
        .weight_exp_o  (tmu_exp),
        .exp_valid_o   (tmu_exp_valid)
    );

    //══════════════════════════════════════════════════════════════
    // TRANS_INT37 — INT37 restoration (FP/MX scenarios: 7 steps)
    //══════════════════════════════════════════════════════════════
    wire [36:0] int37_restored;
    wire        int37_valid;
    wire        needs_restore = !input_prec[3] ? 1'b0 : 1'b1;  // FP/MX→1

    trans_int37 u_trans_int37 (
        .clk            (compute_clk),
        .rst_n          (rst_n),
        .sample_en      (ctrl_post_sample),
        .input_wd       (input_prec[2:0]),
        .needs_restore  (needs_restore),
        .psum_i         (saccum_result[10:0]),
        .psum_valid_i   (saccum_valid),
        .int37_o        (int37_restored),
        .int37_valid_o  (int37_valid)
    );

    //══════════════════════════════════════════════════════════════
    // Mantissa Mux — route INT37 result to output channels
    //══════════════════════════════════════════════════════════════
    mantissa_mux u_mantissa_mux (
        .clk            (compute_clk),
        .rst_n          (rst_n),
        .sample_en      (ctrl_format_sample),
        .accum_result_i ({7'd0, int37_restored[17:0]}),  // simplified
        .accum_valid_i  (int37_valid),
        .weight_prec    (weight_prec),
        .mask_en        (mask_en),
        .manti_o        (o_manti)
    );

    //══════════════════════════════════════════════════════════════
    // Exponent Mux — route exponent to output
    //══════════════════════════════════════════════════════════════
    exponent_mux u_exponent_mux (
        .clk          (compute_clk),
        .rst_n        (rst_n),
        .sample_en    (ctrl_format_sample),
        .dcim_exp_i   (dcim_o_exp),
        .weight_prec  (weight_prec),
        .mask_en      (mask_en),
        .exp_o        (o_exp)
    );

    //── Output flag ───────────────────────────────────────────────
    assign o_data_flag = ctrl_format_sample;

    //══════════════════════════════════════════════════════════════
    // Trans INT37 — INT37 format conversion (placeholder)
    //══════════════════════════════════════════════════════════════

    //══════════════════════════════════════════════════════════════
    // CBIST Top — Memory BIST + Logic BIST
    //══════════════════════════════════════════════════════════════
    cbist_top u_cbist (
        .clk            (allon_clk),
        .rst_n          (rst_n),
        .bist_mode      (dft_bist_mode),
        .bist_start     (dft_bist_start),
        .mbist_en       (dft_mbist_en),
        .lbist_en       (dft_lbist_en),
        .alg_sel        (dft_alg_sel),
        .ram_cen        (dft_ram_cen),
        .ram_wen        (dft_ram_wen),
        .ram_addr       (dft_ram_addr),
        .ram_q          (dft_ram_q),
        .alg_end        (dft_alg_end),
        .atpg_end       (dft_atpg_end),
        .lcomp_go       (dft_lcomp_go),
        .mcomp_go       (dft_mcomp_go)
    );

endmodule
