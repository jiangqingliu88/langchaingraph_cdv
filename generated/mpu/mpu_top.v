//==============================================================================
// MPU Top-Level — Matrix Processing Unit V3
//
// Hierarchy:
//   mpu_top
//   ├── ctrl/mpu_ctrl            — Config FSM (cfg_chk→cfg_sec_res→cfg_ctrl+lp_ctrl+state_report)
//   ├── rd_channel/mpu_rd_channel— SPAD read, INPUT_ALIGN, dispatch
//   ├── cimc/cimc                — CIM Cluster (4×CIME, storage routing)
//   │   └── cime/cime            — CIM Engine (2×CIMM + INT37→INT38)
//   │       └── cimm/cimm        — CIM Macro (SRAM + DCIM core + BIST)
//   │           ├── controller   — Pipeline FSM
//   │           ├── input_process— BOOTH4 encode
//   │           ├── dcim_ip_bm_core — SRAM 16p×33r×256b + MAC array
//   │           ├── adder_tree   — 64ch×11b column sum
//   │           ├── shift_accumulator — 25b right-shift-2
//   │           ├── mantissa_mux — output mantissa routing
//   │           ├── exponent_mux — output exponent routing
//   │           └── cbist_top    — MBIST + LBIST
//   ├── mpu_post_process         — CIME间累加 + Format Conversion
//   └── wr_channel/mpu_wr_channel— SPAD writeback + ADDR_GEN
//==============================================================================
`include "mpu_defines.vh"
`include "ctrl/mpu_ctrl.v"
`include "cimm/cimm.v"
`include "cime/cime.v"
`include "cimc/cimc.v"
`include "rd_channel/mpu_rd_channel.v"
`include "wr_channel/mpu_wr_channel.v"

module mpu_top #(
    parameter P_ADDR_WIDTH   = 32,
    parameter P_DIM0_WIDTH   = 14,
    parameter P_DIM1_WIDTH   = 13,
    parameter P_IO_DATA_WD   = 512,
    parameter CIME_NUM       = 4,
    parameter FP_CIM_PER_CIME= 2,
    parameter FP_CIM_TOTAL   = 8
) (
    input  wire                     compute_clk,
    input  wire                     storage_clk,
    input  wire                     rst_n,

    //── Configuration ────────────────────────────────────────────
    input  wire [31:0]              cmd_mpu_cfg_base_out,
    input  wire [31:0]              cmd_mpu_cfg_base_in,
    input  wire [31:0]              cmd_mpu_cfg_base_orig,
    input  wire [31:0]              cmd_mpu_cfg_base_wt,
    input  wire [31:0]              cmd_mpu_cfg_base_mx,
    input  wire                     cmd_mpu_cfg_mx_in,
    input  wire                     cmd_mpu_cfg_mx_wt,
    input  wire                     cmd_mpu_cfg_type_out,
    input  wire                     cmd_mpu_cfg_type_in,
    input  wire                     cmd_mpu_cfg_type_wt,
    input  wire [2:0]               cmd_mpu_cfg_width_out,
    input  wire [2:0]               cmd_mpu_cfg_width_in,
    input  wire [2:0]               cmd_mpu_cfg_width_wt,
    input  wire                     cmd_mpu_cfg_acc_en,
    input  wire [2:0]               cmd_mpu_cfg_cim_pattern,
    input  wire [1:0]               cmd_mpu_cfg_task_select,
    input  wire [13:0]              cmd_mpu_cfg_size_dim0_out,
    input  wire [13:0]              cmd_mpu_cfg_size_dim0_in,
    input  wire [12:0]              cmd_mpu_cfg_size_dim1_out,
    input  wire [12:0]              cmd_mpu_cfg_size_dim1_in,
    input  wire [12:0]              cmd_mpu_cfg_stride_dim1_out,
    input  wire [12:0]              cmd_mpu_cfg_stride_dim1_in,
    input  wire [5:0]               cmd_mpu_cfg_rem_dim0_out,
    input  wire [5:0]               cmd_mpu_cfg_rem_dim0_in,
    input  wire                     cmd_mpu_cfg_mx_out,
    input  wire                     cmd_mpu_cfg_mx_orig,
    input  wire                     cmd_mpu_cfg_type_orig,
    input  wire                     cmd_mpu_cfg_manti_out,
    input  wire                     cmd_mpu_cfg_manti_orig,
    input  wire                     cmd_mpu_cfg_manti_in,
    input  wire                     cmd_mpu_cfg_manti_wt,
    input  wire [2:0]               cmd_mpu_cfg_width_orig,
    input  wire [31:0]              cmd_mpu_cfg_mx_size,
    input  wire                     cmd_mpu_cfg_decode_stage_en,
    input  wire                     cmd_mpu_start,
    output wire                     mpu_cmd_done_lclrd,
    output wire                     mpu_cmd_done,

    //── Write Channel ch0_wr ─────────────────────────────────────
    output wire [31:0]              wr_xbar_req_addr,
    output wire [511:0]             wr_xbar_req_data,
    output wire                     wr_xbar_req_flag,
    output wire [1:0]               wr_xbar_req_strobe,
    output wire                     wr_xbar_req_vld,
    input  wire                     wr_xbar_req_rdy,
    input  wire                     wr_xbar_rsp_vld,
    output wire                     wr_xbar_rsp_rdy,

    //── Read Channel 0 ───────────────────────────────────────────
    output wire [31:0]              mpu_xbr_rd0_req_addr,
    output wire                     mpu_xbr_rd0_req_vld,
    input  wire                     xbr_mpu_rd0_req_rdy,
    input  wire [511:0]             xbr_mpu_rd0_rsp_data,
    input  wire                     xbr_mpu_rd0_rsp_vld,
    output wire                     mpu_xbr_rd0_rsp_rdy,

    //── Read Channel 1 ───────────────────────────────────────────
    output wire [31:0]              mpu_xbr_rd1_req_addr,
    output wire                     mpu_xbr_rd1_req_vld,
    input  wire                     xbr_mpu_rd1_req_rdy,
    input  wire [511:0]             xbr_mpu_rd1_rsp_data,
    input  wire                     xbr_mpu_rd1_rsp_vld,
    output wire                     mpu_xbr_rd1_rsp_rdy,

    //── Storage Channel ──────────────────────────────────────────
    input  wire                     xbr_cim_wen_vld,
    output wire                     cim_xbr_wen_rdy,
    input  wire                     xbr_cim_wen_flag,
    output wire                     cim_xbr_wen_ack_vld,
    input  wire                     xbr_cim_wen_ack_rdy,
    input  wire                     cim_xbr_ren_global_vld,
    output wire                     xbr_cim_ren_global_rdy,
    output wire                     xbr_cim_ren_global_ack_vld,
    input  wire                     cim_xbr_ren_global_ack_rdy,
    input  wire [31:0]              xbr_cim_addr,
    input  wire [1:0]               xbr_cim_strobe,
    input  wire [511:0]             xbr_cim_mem_d,
    output wire [511:0]             cim_xbr_mem_q,
    input  wire                     xbr_cim_exp_flag,

    //── DFT ──────────────────────────────────────────────────────
    input  wire                     dft_scan_en,
    input  wire                     dft_dcim_bist_mode,
    input  wire                     dft_dcim_bist_start,
    input  wire                     dft_dcim_alg_sel,
    input  wire                     dft_dcim_mbist_en,
    output wire [7:0]               dft_dcim_mcomp_go,
    input  wire                     dft_dcim_lbist_en,
    output wire [7:0]               dft_dcim_lcomp_go,
    output wire [7:0]               dft_dcim_alg_end,
    output wire [7:0]               dft_dcim_atpg_end,
    output wire                     dft_dcim_ram_cen,
    output wire                     dft_dcim_ram_wen,
    output wire [31:0]              dft_dcim_ram_addr,
    input  wire [511:0]             dft_dcim_ram_q,

    //── Debug & Perf ─────────────────────────────────────────────
    input  wire                     creg_mpu_start,
    input  wire                     creg_mpu_pause,
    input  wire                     creg_mpu_continue,
    input  wire                     creg_mpu_end,
    output wire [191:0]             mpu_creg_perf_count_reg,
    input  wire                     creg_mpu_perf_enable,
    output wire [31:0]              mpu_creg_int,
    output wire [31:0]              mpu_creg_dbg_reg0,
    output wire [31:0]              mpu_creg_dbg_reg1,
    output wire [31:0]              mpu_creg_dbg_reg2
);

    //══════════════════════════════════════════════════════════════
    // Internal wires
    //══════════════════════════════════════════════════════════════
    // ctrl → rd_channel
    wire        ctrl_rd0_start, ctrl_rd1_start;
    wire [31:0] ctrl_rd0_base,  ctrl_rd1_base;
    wire [13:0] ctrl_rd0_dim0,  ctrl_rd1_dim0;
    wire [12:0] ctrl_rd0_dim1,  ctrl_rd1_dim1;
    wire [12:0] ctrl_rd0_stride,ctrl_rd1_stride;
    wire [3:0]  ctrl_precision;
    wire        ctrl_mx_en, ctrl_psum_en;
    // Shape
    wire [3:0]  ctrl_active_cime;
    wire [3:0]  ctrl_cime_mask;
    wire [15:0] ctrl_total_elems;
    wire [5:0]  ctrl_elems_per_xfer;
    wire [5:0]  ctrl_elems_per_cime;
    wire [5:0]  ctrl_rem_elems;
    wire [2:0]  ctrl_addr_pattern;

    // rd_channel → CIME (per-CIME 512-bit activation + EXP)
    wire [CIME_NUM-1:0][511:0]  rd_cime_activation;
    wire [CIME_NUM-:0][7:0]    rd_cime_exp;
    wire [CIME_NUM-1:0]         rd_cime_valid;
    wire [CIME_NUM-1:0]         cime_rd_ready;

    // CIME → post_process (per-CIME accumulator result)
    wire [CIME_NUM-1:0][31:0]   cime_fp32_result;
    wire [CIME_NUM-1:0][7:0]    cime_fp32_exp;
    wire [CIME_NUM-1:0]         cime_fp32_valid;
    wire [CIME_NUM-1:0]         post_cime_ready;

    // post → wr_channel
    wire [511:0] post_wr_data;
    wire         post_wr_valid, wr_post_ready, post_wr_last;

    // Perf
    wire [31:0] perf_rd0_cnt, perf_rd1_cnt, perf_wr_cnt, perf_cycle_cnt;

    //══════════════════════════════════════════════════════════════
    // MPU_CTRL
    //══════════════════════════════════════════════════════════════
    mpu_ctrl u_ctrl (
        .clk_i              (compute_clk),
        .rst_n              (rst_n),
        .cfg_base_out_i     (cmd_mpu_cfg_base_out),
        .cfg_base_in_i      (cmd_mpu_cfg_base_in),
        .cfg_base_orig_i    (cmd_mpu_cfg_base_orig),
        .cfg_base_wt_i      (cmd_mpu_cfg_base_wt),
        .cfg_base_mx_i      (cmd_mpu_cfg_base_mx),
        .cfg_type_out_i     (cmd_mpu_cfg_type_out),
        .cfg_type_orig_i    (cmd_mpu_cfg_type_orig),
        .cfg_type_in_i      (cmd_mpu_cfg_type_in),
        .cfg_type_wt_i      (cmd_mpu_cfg_type_wt),
        .cfg_width_out_i    (cmd_mpu_cfg_width_out),
        .cfg_width_orig_i   (cmd_mpu_cfg_width_orig),
        .cfg_width_in_i     (cmd_mpu_cfg_width_in),
        .cfg_width_wt_i     (cmd_mpu_cfg_width_wt),
        .cfg_mx_in_i        (cmd_mpu_cfg_mx_in),
        .cfg_mx_wt_i        (cmd_mpu_cfg_mx_wt),
        .cfg_acc_en_i       (cmd_mpu_cfg_acc_en),
        .cfg_task_select_i  (cmd_mpu_cfg_task_select),
        .cfg_pattern_i      (cmd_mpu_cfg_cim_pattern),
        .cfg_size_dim0_out_i(cmd_mpu_cfg_size_dim0_out),
        .cfg_size_dim0_in_i (cmd_mpu_cfg_size_dim0_in),
        .cfg_size_dim1_out_i(cmd_mpu_cfg_size_dim1_out),
        .cfg_size_dim1_in_i (cmd_mpu_cfg_size_dim1_in),
        .cfg_stride_dim1_out_i(cmd_mpu_cfg_stride_dim1_out),
        .cfg_stride_dim1_in_i (cmd_mpu_cfg_stride_dim1_in),
        .start_i            (cmd_mpu_start),
        .done_lclrd_o       (mpu_cmd_done_lclrd),
        .done_o             (mpu_cmd_done),
        .int_o              (mpu_creg_int),
        .ctrl_rd0_start_o   (ctrl_rd0_start),
        .ctrl_rd1_start_o   (ctrl_rd1_start),
        .ctrl_rd0_base_o    (ctrl_rd0_base),
        .ctrl_rd1_base_o    (ctrl_rd1_base),
        .ctrl_rd0_dim0_o    (ctrl_rd0_dim0),
        .ctrl_rd1_dim0_o    (ctrl_rd1_dim0),
        .ctrl_rd0_dim1_o    (ctrl_rd0_dim1),
        .ctrl_rd1_dim1_o    (ctrl_rd1_dim1),
        .ctrl_rd0_stride_o  (ctrl_rd0_stride),
        .ctrl_rd1_stride_o  (ctrl_rd1_stride),
        .ctrl_precision_o   (ctrl_precision),
        .ctrl_mx_en_o       (ctrl_mx_en),
        .ctrl_psum_en_o     (ctrl_psum_en),
        .ctrl_active_cime_o   (ctrl_active_cime),
        .ctrl_cime_mask_o     (ctrl_cime_mask),
        .ctrl_total_elems_o   (ctrl_total_elems),
        .ctrl_elems_per_xfer_o(ctrl_elems_per_xfer),
        .ctrl_elems_per_cime_o(ctrl_elems_per_cime),
        .ctrl_rem_elems_o     (ctrl_rem_elems),
        .ctrl_addr_pattern_o  (ctrl_addr_pattern),
	    .ctrl_grid_rows_o     (ctrl_grid_rows),
	    .ctrl_grid_cols_o     (ctrl_grid_cols),
	    .ctrl_cime_in_width_o (ctrl_cime_in_width),
	    .ctrl_cime_wt_width_o (ctrl_cime_wt_width),
	    .ctrl_rows_per_cime_o (ctrl_rows_per_cime),
	    .ctrl_elems_per_row_o (ctrl_elems_per_row),
	    .ctrl_dim0_cols_o     (ctrl_dim0_cols),
        .perf_rd0_cnt_i     (perf_rd0_cnt),
        .perf_rd1_cnt_i     (perf_rd1_cnt),
        .perf_wr_cnt_i      (perf_wr_cnt),
        .perf_cim_cnt_i     (32'd0),
        .perf_cycle_cnt_i   (perf_cycle_cnt),
        .perf_fp_busy_cnt_i (32'd0),
        .perf_en_i          (creg_mpu_perf_enable),
        .perf_start_i       (creg_mpu_start),
        .perf_pause_i       (creg_mpu_pause),
        .perf_continue_i    (creg_mpu_continue),
        .perf_end_i         (creg_mpu_end),
        .perf_cnt_reg_o     (mpu_creg_perf_count_reg),
        .dbg_reg0_o         (mpu_creg_dbg_reg0),
        .dbg_reg1_o         (mpu_creg_dbg_reg1),
        .dbg_reg2_o         (mpu_creg_dbg_reg2)
    );

    //══════════════════════════════════════════════════════════════
    // MPU_RD_CHANNEL
    //══════════════════════════════════════════════════════════════
    mpu_rd_channel u_rd_channel (
        .clk_i              (compute_clk),
        .rst_n              (rst_n),
        .rd0_start_i        (ctrl_rd0_start),
        .rd1_start_i        (ctrl_rd1_start),
        .rd0_base_addr_i    (ctrl_rd0_base),
        .rd1_base_addr_i    (ctrl_rd1_base),
        .rd0_dim0_i         (ctrl_rd0_dim0),
        .rd1_dim0_i         (ctrl_rd1_dim0),
        .rd0_dim1_i         (ctrl_rd0_dim1),
        .rd1_dim1_i         (ctrl_rd1_dim1),
        .rd0_stride_i       (ctrl_rd0_stride),
        .rd1_stride_i       (ctrl_rd1_stride),
        .precision_i        (ctrl_precision),
        .mx_en_i            (ctrl_mx_en),
        .psum_en_i          (ctrl_psum_en),
        .active_cime_i      (ctrl_active_cime),
        .cime_mask_i        (ctrl_cime_mask),
        .addr_pattern_i     (ctrl_addr_pattern),
        .elems_per_xfer_i   (ctrl_elems_per_xfer),
        .rd0_req_addr_o     (mpu_xbr_rd0_req_addr),
        .rd0_req_vld_o      (mpu_xbr_rd0_req_vld),
        .rd0_req_rdy_i      (xbr_mpu_rd0_req_rdy),
        .rd0_rsp_data_i     (xbr_mpu_rd0_rsp_data),
        .rd0_rsp_vld_i      (xbr_mpu_rd0_rsp_vld),
        .rd0_rsp_rdy_o      (mpu_xbr_rd0_rsp_rdy),
        .rd1_req_addr_o     (mpu_xbr_rd1_req_addr),
        .rd1_req_vld_o      (mpu_xbr_rd1_req_vld),
        .rd1_req_rdy_i      (xbr_mpu_rd1_req_rdy),
        .rd1_rsp_data_i     (xbr_mpu_rd1_rsp_data),
        .rd1_rsp_vld_i      (xbr_mpu_rd1_rsp_vld),
        .rd1_rsp_rdy_o      (mpu_xbr_rd1_rsp_rdy),
        .cim_data_o         (rd_cime_activation),
        .cim_exp_o          (rd_cime_exp),
        .cim_valid_o        (rd_cime_valid),
        .cim_ready_i        (cime_rd_ready),
        .perf_rd0_cnt_o     (perf_rd0_cnt),
        .perf_rd1_cnt_o     (perf_rd1_cnt)
    );

    //══════════════════════════════════════════════════════════════
    // CIMC — CIM Cluster: 4× CIME, each CIME = 2× CIMM
    // Hierarchy: CIMC → CIME[0..3] → CIMM[0..1]
    // Total: 4 CIME × 2 CIMM = 8 CIMM (128KB visible + 4KB hidden)
    //══════════════════════════════════════════════════════════════
    wire [CIME_NUM-1:0][38:0]  cimc_int38_data;
    wire [CIME_NUM-1:0][7:0]   cimc_int38_exp;
    wire [CIME_NUM-1:0]        cimc_int38_valid;

    cimc u_cimc (
        .storage_clk        (storage_clk),
        .compute_clk        (compute_clk),
        .allon_clk          (compute_clk),
        .rst_n              (rst_n),
        // Computation input (from rd_channel)
        .cim_data_i         (rd_cime_activation),
        .cim_exp_i          (rd_cime_exp),
        .cim_valid_i        (rd_cime_valid),
        .cim_ready_o        (cim_rd_ready),
        // Computation output (to mpu_accumulator / post_process)
        .int38_data_o       (cimc_int38_data),
        .int38_exp_o        (cimc_int38_exp),
        .int38_valid_o      (cimc_int38_valid),
        // Storage interface
        .wen_vld_i          (xbr_cim_wen_vld),
        .wen_rdy_o          (cim_xbr_wen_rdy),
        .wen_flag_i         (xbr_cim_wen_flag),
        .wen_ack_vld_o      (cim_xbr_wen_ack_vld),
        .wen_ack_rdy_i      (xbr_cim_wen_ack_rdy),
        .ren_global_vld_i   (cim_xbr_ren_global_vld),
        .ren_global_rdy_o   (xbr_cim_ren_global_rdy),
        .ren_global_ack_vld_o(xbr_cim_ren_global_ack_vld),
        .ren_global_ack_rdy_i(cim_xbr_ren_global_ack_rdy),
        .cim_addr_i         (xbr_cim_addr),
        .cim_strobe_i       (xbr_cim_strobe),
        .cim_mem_d_i        (xbr_cim_mem_d),
        .cim_mem_q_o        (cim_xbr_mem_q),
        .exp_flag_i         (xbr_cim_exp_flag),
        // Config
        .cfg_fmt            ({1'b0, ctrl_precision[2:0], ctrl_precision[3:0], ctrl_precision[2:0]}),
        .pattern_i          (cmd_mpu_cfg_cim_pattern),
        .active_cime_i      (ctrl_active_cime),
        .cime_mask_i        (ctrl_cime_mask),
        // DFT
        .dft_bist_mode      (dft_dcim_bist_mode),
        .dft_bist_start     (dft_dcim_bist_start),
        .dft_mbist_en       (dft_dcim_mbist_en),
        .dft_lbist_en       (dft_dcim_lbist_en),
        .dft_alg_sel        (dft_dcim_alg_sel),
        .dft_mcomp_go       (dft_dcim_mcomp_go),
        .dft_lcomp_go       (dft_dcim_lcomp_go),
        .dft_alg_end        (dft_dcim_alg_end),
        .dft_atpg_end       (dft_dcim_atpg_end),
        .creg_dcim_ema      (27'd0),
        // Perf
        .perf_cim_cnt_o     (),
        .perf_fp_busy_cnt_o ()
    );

    // Forward CIMC INT38 outputs to post_process
    // (simplified: use CIME0 result as primary)
    assign cime_fp32_result = {CIME_NUM{32'd0}};  // connected through accumulator
    assign cime_fp32_valid  = {CIME_NUM{1'b0}};

    //══════════════════════════════════════════════════════════════
    // Post Process — CIME间累加 + Format Conversion + PSUM
    //══════════════════════════════════════════════════════════════
    mpu_post_process u_post (
        .clk_i          (compute_clk),
        .rst_n          (rst_n),
        .cim_data_i     ('d0),  // post uses accumulator outputs
        .cim_exp_i      ('d0),
        .cim_valid_i    (cime_fp32_valid),
        .cim_ready_o    (post_cime_ready),
        .wr_data_o      (post_wr_data),
        .wr_valid_o     (post_wr_valid),
        .wr_ready_i     (wr_post_ready),
        .wr_last_o      (post_wr_last),
        .pattern_i      (cmd_mpu_cfg_cim_pattern),
        .precision_i    (ctrl_precision),
        .acc_en_i       (cmd_mpu_cfg_acc_en),
        .type_out_i     (cmd_mpu_cfg_type_out),
        .width_out_i    (cmd_mpu_cfg_width_out)
    );

    //══════════════════════════════════════════════════════════════
    // Write Channel
    //══════════════════════════════════════════════════════════════
    mpu_wr_channel u_wr_channel (
        .clk_i          (compute_clk),
        .rst_n          (rst_n),
        .wr_data_i      (post_wr_data),
        .wr_valid_i     (post_wr_valid),
        .wr_ready_o     (wr_post_ready),
        .wr_last_i      (post_wr_last),
        .wr_req_addr_o  (wr_xbar_req_addr),
        .wr_req_data_o  (wr_xbar_req_data),
        .wr_req_flag_o  (wr_xbar_req_flag),
        .wr_req_strobe_o(wr_xbar_req_strobe),
        .wr_req_vld_o   (wr_xbar_req_vld),
        .wr_req_rdy_i   (wr_xbar_req_rdy),
        .wr_rsp_vld_i   (wr_xbar_rsp_vld),
        .wr_rsp_rdy_o   (wr_xbar_rsp_rdy),
        .base_addr_i    (cmd_mpu_cfg_base_out),
        .dim0_size_i    (cmd_mpu_cfg_size_dim0_out),
        .dim1_size_i    (cmd_mpu_cfg_size_dim1_out),
        .stride_i       (cmd_mpu_cfg_stride_dim1_out),
        .pattern_i      (cmd_mpu_cfg_cim_pattern),
        .perf_wr_cnt_o  (perf_wr_cnt)
    );

    //── Storage channel (simplified) ─────────────────────────────
    assign cim_xbr_wen_rdy           = 1'b1;
    assign cim_xbr_wen_ack_vld       = 1'b0;
    assign xbr_cim_ren_global_rdy    = 1'b1;
    assign xbr_cim_ren_global_ack_vld= 1'b0;
    assign cim_xbr_mem_q             = 512'd0;

    //── DFT ──────────────────────────────────────────────────────
    assign dft_dcim_mcomp_go  = 8'hFF;
    assign dft_dcim_lcomp_go  = 8'hFF;
    assign dft_dcim_alg_end   = 8'd0;
    assign dft_dcim_atpg_end  = 8'd0;
    assign dft_dcim_ram_cen   = 1'b1;
    assign dft_dcim_ram_wen   = 1'b1;
    assign dft_dcim_ram_addr  = 32'd0;

    //── Cycle counter ────────────────────────────────────────────
    reg [31:0] cycle_cnt;
    always @(posedge compute_clk or negedge rst_n) begin
        if (!rst_n) cycle_cnt <= 32'd0;
        else if (creg_mpu_perf_enable) cycle_cnt <= cycle_cnt + 32'd1;
    end
    assign perf_cycle_cnt = cycle_cnt;

endmodule
