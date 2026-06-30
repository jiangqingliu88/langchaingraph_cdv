//==============================================================================
// CIMC — CIM Cluster: 4× CIME + CIME间累加 + Storage routing
// Spec: CIMC = 由多个CIME组成的核心计算部件
//       存储部分作为Local Memory中的一部分存在
// Total: 4 CIME × 2 CIMM = 8 CIMM, 16 pages each → 128KB visible + 4KB hidden
//==============================================================================
module cimc #(
    parameter CIME_NUM       = 4,
    parameter CIMM_PER_CIME  = 2,
    parameter CIMM_TOTAL     = 8,
    parameter P_IO_DATA_WD   = 512,
    parameter CIMC_ADDR_WD   = 13,
    parameter P_ADDR_WIDTH   = 32
) (
    input  wire         storage_clk,
    input  wire         compute_clk,
    input  wire         allon_clk,
    input  wire         rst_n,

    //── Computation input (from RD_CHANNEL) ──────────────────────
    input  wire [CIME_NUM-1:0][P_IO_DATA_WD-1:0] cim_data_i,
    input  wire [CIME_NUM-1:0][7:0]              cim_exp_i,
    input  wire [CIME_NUM-1:0]                   cim_valid_i,
    output wire [CIME_NUM-1:0]                   cim_ready_o,

    //── Computation output (to POST_PROCESS) ─────────────────────
    output wire [CIME_NUM-1:0][38:0]             int38_data_o,   // per-CIME INT38
    output wire [CIME_NUM-1:0][7:0]              int38_exp_o,
    output wire [CIME_NUM-1:0]                   int38_valid_o,

    //── Storage interface (from SPAD_MPU / XBAR) ──────────────────
    input  wire                     wen_vld_i,
    output wire                     wen_rdy_o,
    input  wire                     wen_flag_i,
    output wire                     wen_ack_vld_o,
    input  wire                     wen_ack_rdy_i,
    input  wire                     ren_global_vld_i,
    output wire                     ren_global_rdy_o,
    output wire                     ren_global_ack_vld_o,
    input  wire                     ren_global_ack_rdy_i,
    input  wire [P_ADDR_WIDTH-1:0]  cim_addr_i,
    input  wire [1:0]               cim_strobe_i,    // 256-bit granularity
    input  wire [P_IO_DATA_WD-1:0]  cim_mem_d_i,     // 512-bit write data
    output wire [P_IO_DATA_WD-1:0]  cim_mem_q_o,     // 512-bit read data
    input  wire                     exp_flag_i,       // EXP access flag

    //── Config ────────────────────────────────────────────────────
    input  wire [10:0]              cfg_fmt,          // precision format
    input  wire [2:0]               pattern_i,        // PATTERN2 / PATTERN3
    input  wire [3:0]               active_cime_i,    // 1-4 active CIMEs
    input  wire [3:0]               cime_mask_i,      // per-CIME enable

    //── DFT ──────────────────────────────────────────────────────
    input  wire                     dft_bist_mode,
    input  wire                     dft_bist_start,
    input  wire                     dft_mbist_en,
    input  wire                     dft_lbist_en,
    input  wire                     dft_alg_sel,
    output wire [CIMM_TOTAL-1:0]    dft_mcomp_go,
    output wire [CIMM_TOTAL-1:0]    dft_lcomp_go,
    output wire [CIMM_TOTAL-1:0]    dft_alg_end,
    output wire [CIMM_TOTAL-1:0]    dft_atpg_end,
    input  wire [26:0]              creg_dcim_ema,

    //── Perf ──────────────────────────────────────────────────────
    output reg  [31:0]              perf_cim_cnt_o,
    output reg  [31:0]              perf_fp_busy_cnt_o
);

    //══════════════════════════════════════════════════════════════
    // Address mapping: XBAR[31:0] → {CIME, CIMM, PAGE, ROW}
    // Uses addr_map module for PATTERN2/PATTERN3 decoding
    //
    // CIMM EXP internal addresses (10-bit = {CIME[1:0],CIMM,3'b010,3'b000}):
    //   000100000→CIME0/CIMM0  001100000→CIME0/CIMM1
    //   010100000→CIME1/CIMM0  011100000→CIME1/CIMM1
    //   100100000→CIME2/CIMM0  101100000→CIME2/CIMM1
    //   110100000→CIME3/CIMM0  111100000→CIME3/CIMM1
    //══════════════════════════════════════════════════════════════
    wire [1:0]  addr_cime;
    wire        addr_cimm;
    wire [3:0]  addr_page;
    wire [5:0]  addr_row;
    wire [7:0]  addr_cim_offset;
    wire        addr_is_exp;

    addr_map u_addr_map (
        .xbar_addr_i    (cim_addr_i),
        .pattern_i      (pattern_i),
        .is_exp_access_i(exp_flag_i),
        .cime_sel_o     (addr_cime),
        .cimm_sel_o     (addr_cimm),
        .page_o         (addr_page),
        .row_o          (addr_row),
        .cim_offset_o   (addr_cim_offset),
        .is_exp_row_o   (addr_is_exp)
    );

    // Per-CIMM select signals (one-hot decoded)
    wire [CIMM_TOTAL-1:0] cimm_sel;
    genvar si;
    generate
    for (si = 0; si < CIME_NUM; si = si + 1) begin : addr_decode
        assign cimm_sel[si*2 + 0] = (addr_cime == si) && (addr_cimm == 1'b0);
        assign cimm_sel[si*2 + 1] = (addr_cime == si) && (addr_cimm == 1'b1);
    end
    endgenerate

    // Per-CIMM write enable (from storage channel)
    wire [CIMM_TOTAL-1:0] cimm_wen;
    wire [CIMM_TOTAL-1:0] cimm_ren_global;
    wire [CIMM_TOTAL-1:0] cimm_ren_local;
    wire [CIMM_TOTAL-1:0] cimm_cen;

    genvar ci;
    generate
    for (ci = 0; ci < CIMM_TOTAL; ci = ci + 1) begin : cimm_ctrl
        assign cimm_wen[ci]        = wen_vld_i && cimm_sel[ci];
        assign cimm_ren_global[ci] = ren_global_vld_i && cimm_sel[ci];
        assign cimm_ren_local[ci]  = 1'b0;  // from ctrl
        assign cimm_cen[ci]        = cim_valid_i[ci/2] && cime_mask_i[ci/2];
    end
    endgenerate

    // Per-CIMM address (10-bit: {page[3:0], row[5:0]})
    // Using addr_map decoded page/row per PATTERN
    wire [CIMM_TOTAL-1:0][9:0] cimm_addr;
    generate
    for (ci = 0; ci < CIMM_TOTAL; ci = ci + 1) begin : cimm_addr_gen
        assign cimm_addr[ci] = {addr_page, addr_row};  // {page[3:0], row[5:0]}
    end
    endgenerate

    // Per-CIMM write data routing (256-bit each, from 512-bit input)
    // strobe: 01=lower 256b, 10=upper 256b, 11=full 512b
    wire [CIMM_TOTAL-1:0][255:0] cimm_mem_d;
    generate
    for (ci = 0; ci < CIMM_TOTAL; ci = ci + 1) begin : cimm_wdata
        assign cimm_mem_d[ci] = cim_strobe_i[0] ? cim_mem_d_i[255:0] :
                                cim_strobe_i[1] ? cim_mem_d_i[511:256] : 256'd0;
    end
    endgenerate

    // Per-CIMM read data collection
    wire [CIMM_TOTAL-1:0][255:0] cimm_mem_q;
    assign cim_mem_q_o = {cimm_mem_q[1], cimm_mem_q[0]};  // simplified: CIME0 CIMM0+1

    //══════════════════════════════════════════════════════════════
    // CIME Array: 4× CIME, each with 2× CIMM
    //══════════════════════════════════════════════════════════════
    wire [CIME_NUM-1:0][CIMM_PER_CIME-1:0][255:0] cime_cimm_mem_q;
    wire [CIME_NUM-1:0][CIMM_PER_CIME-1:0][591:0] cime_cimm_manti;
    wire [CIME_NUM-1:0][CIMM_PER_CIME-1:0][143:0] cime_cimm_exp;
    wire [CIME_NUM-1:0][CIMM_PER_CIME-1:0]        cime_cimm_flag;
    wire [CIME_NUM-1:0][38:0]                     cime_int38_data;
    wire [CIME_NUM-1:0][7:0]                      cime_int38_exp;
    wire [CIME_NUM-1:0]                           cime_int38_valid;
    wire [CIME_NUM-1:0][CIMM_PER_CIME-1:0]        cime_dft_alg_end;
    wire [CIME_NUM-1:0][CIMM_PER_CIME-1:0]        cime_dft_mcomp_go;
    wire [CIME_NUM-1:0][CIMM_PER_CIME-1:0]        cime_dft_lcomp_go;

    genvar cime_i;
    generate
    for (cime_i = 0; cime_i < CIME_NUM; cime_i = cime_i + 1) begin : cime_gen

        cime u_cime (
            .storage_clk    (storage_clk),
            .compute_clk    (compute_clk),
            .allon_clk      (allon_clk),
            .rst_n          (rst_n),
            .cimm_wen       (cimm_wen[cime_i*2 +: 2]),
            .cimm_ren_global(cimm_ren_global[cime_i*2 +: 2]),
            .cimm_ren_local (cimm_ren_local[cime_i*2 +: 2]),
            .cimm_cen       (cimm_cen[cime_i*2 +: 2]),
            .cfg_fmt        (cfg_fmt),
            .mask_en        (64'h0000_0000_FFFF_FFFF),  // 32ch active
            .cimm_addr      (cimm_addr[cime_i*2 +: 2]),
            .cimm_mem_d     (cimm_mem_d[cime_i*2 +: 2]),
            .i_data         (cim_data_i[cime_i]),
            .exp            ({1'b0, cim_exp_i[cime_i]}),
            .share_exp      (8'd0),
            .cimm_mem_q     (cime_cimm_mem_q[cime_i]),
            .cimm_o_manti   (cime_cimm_manti[cime_i]),
            .cimm_o_exp     (cime_cimm_exp[cime_i]),
            .cimm_o_data_flag(cime_cimm_flag[cime_i]),
            .int38_result_o (cime_int38_data[cime_i]),
            .int38_exp_o    (cime_int38_exp[cime_i]),
            .int38_valid_o  (cime_int38_valid[cime_i]),
            .dft_bist_mode  (dft_bist_mode),
            .dft_bist_start (dft_bist_start),
            .dft_mbist_en   (dft_mbist_en),
            .dft_lbist_en   (dft_lbist_en),
            .dft_alg_sel    (dft_alg_sel),
            .dft_alg_end    (cime_dft_alg_end[cime_i]),
            .dft_mcomp_go   (cime_dft_mcomp_go[cime_i]),
            .dft_lcomp_go   (cime_dft_lcomp_go[cime_i]),
            .creg_dcim_ema  (creg_dcim_ema)
        );

        assign cim_ready_o[cime_i] = 1'b1;  // always ready (no backpressure in V3)
    end
    endgenerate

    //── Collect per-CIME outputs ──────────────────────────────────
    assign int38_data_o  = cime_int38_data;
    assign int38_exp_o   = cime_int38_exp;
    assign int38_valid_o = cime_int38_valid;

    //── Collect per-CIMM mem_q for readback ──────────────────────
    genvar cq;
    generate
    for (cq = 0; cq < CIMM_TOTAL; cq = cq + 1) begin : memq_collect
        assign cimm_mem_q[cq] = cime_cimm_mem_q[cq/2][cq%2];
    end
    endgenerate

    //── Collect DFT outputs ──────────────────────────────────────
    genvar df;
    generate
    for (df = 0; df < CIMM_TOTAL; df = df + 1) begin : dft_collect
        assign dft_alg_end[df]  = cime_dft_alg_end[df/2][df%2];
        assign dft_mcomp_go[df] = cime_dft_mcomp_go[df/2][df%2];
        assign dft_lcomp_go[df] = cime_dft_lcomp_go[df/2][df%2];
        assign dft_atpg_end[df] = 1'b0;  // placeholder
    end
    endgenerate

    //── Storage channel handshake ─────────────────────────────────
    assign wen_rdy_o           = 1'b1;
    assign wen_ack_vld_o       = wen_vld_i;
    assign ren_global_rdy_o    = 1'b1;
    assign ren_global_ack_vld_o= ren_global_vld_i;

    //── Perf counters ────────────────────────────────────────────
    always @(posedge compute_clk or negedge rst_n) begin
        if (!rst_n) begin
            perf_cim_cnt_o     <= 32'd0;
            perf_fp_busy_cnt_o <= 32'd0;
        end else begin
            if (|cim_valid_i)
                perf_cim_cnt_o <= perf_cim_cnt_o + 32'd1;
            if (|cim_valid_i && cfg_fmt[9])  // FP operation
                perf_fp_busy_cnt_o <= perf_fp_busy_cnt_o + 32'd4;
        end
    end

endmodule
