//==============================================================================
// mpu_ctrl — MPU Controller Top-Level
// Sub-modules: cfg_chk → cfg_sec_resolution → cfg_ctrl + lp_ctrl + state_report
//==============================================================================
module mpu_ctrl (
    input  wire         clk_i, rst_n, start_i,
    input  wire [31:0]  cfg_base_out_i, cfg_base_in_i, cfg_base_orig_i,
    input  wire [31:0]  cfg_base_wt_i,  cfg_base_mx_i,
    input  wire         cfg_type_out_i, cfg_type_in_i, cfg_type_wt_i,
    input  wire         cfg_type_orig_i,
    input  wire [2:0]   cfg_width_out_i, cfg_width_in_i, cfg_width_wt_i,
    input  wire [2:0]   cfg_width_orig_i,
    input  wire         cfg_mx_in_i, cfg_mx_wt_i, cfg_acc_en_i,
    input  wire [2:0]   cfg_pattern_i,
    input  wire [1:0]   cfg_task_select_i,
    input  wire [13:0]  cfg_size_dim0_out_i, cfg_size_dim0_in_i,
    input  wire [12:0]  cfg_size_dim1_out_i, cfg_size_dim1_in_i,
    input  wire [12:0]  cfg_stride_dim1_out_i, cfg_stride_dim1_in_i,
    input  wire [31:0]  cfg_mx_size_i,
    output wire         done_lclrd_o, done_o,
    output wire [31:0]  int_o,
    // Control outputs
    output wire         ctrl_rd0_start_o, ctrl_rd1_start_o,
    output wire [31:0]  ctrl_rd0_base_o,  ctrl_rd1_base_o,
    output wire [13:0]  ctrl_rd0_dim0_o,  ctrl_rd1_dim0_o,   // 64B transfer count
    output wire [12:0]  ctrl_rd0_dim1_o,  ctrl_rd1_dim1_o,
    output wire [12:0]  ctrl_rd0_stride_o,ctrl_rd1_stride_o,
    output wire [3:0]   ctrl_precision_o, ctrl_active_cime_o, ctrl_cime_mask_o,
    output wire [15:0]  ctrl_total_elems_o,
    output wire [5:0]   ctrl_elems_per_xfer_o, ctrl_elems_per_cime_o, ctrl_rem_elems_o,
    output wire [2:0]   ctrl_addr_pattern_o,
    output wire         ctrl_mx_en_o, ctrl_psum_en_o,
    // Shape analysis
    output wire [1:0]   ctrl_grid_rows_o, ctrl_grid_cols_o,
    output wire [9:0]   ctrl_cime_in_width_o, ctrl_cime_wt_width_o,
    output wire [5:0]   ctrl_rows_per_cime_o, ctrl_elems_per_row_o,
    output wire [13:0]  ctrl_dim0_cols_o,
    // Perf
    input  wire [31:0]  perf_rd0_i, perf_rd1_i, perf_wr_i, perf_cim_i,
    input  wire [31:0]  perf_cycle_i, perf_fp_busy_i,
    input  wire         perf_en_i, perf_start_i, perf_pause_i, perf_continue_i, perf_end_i,
    output wire [191:0] perf_cnt_reg_o,
    output wire [31:0]  dbg_reg0_o, dbg_reg1_o, dbg_reg2_o
);

    //── cfg_chk ──────────────────────────────────────────────────
    wire        chk_pass;
    wire [31:0] chk_int;        // full 32-bit interrupt from cfg_chk

    cfg_chk u_chk (
        .cfg_base_out_i (cfg_base_out_i), .cfg_base_in_i(cfg_base_in_i),
        .cfg_base_orig_i(cfg_base_orig_i),.cfg_base_wt_i(cfg_base_wt_i),
        .cfg_base_mx_i  (cfg_base_mx_i),
        .cfg_width_in_i (cfg_width_in_i), .cfg_width_out_i(cfg_width_out_i),
        .cfg_width_wt_i (cfg_width_wt_i),
        .cfg_dim0_in_i  (cfg_size_dim0_in_i), .cfg_dim0_out_i(cfg_size_dim0_out_i),
        .cfg_task_i     (cfg_task_select_i),  .cfg_mx_in_i  (cfg_mx_in_i),
        .cfg_mx_size_i  (cfg_mx_size_i),
        .chk_pass_o     (chk_pass), .int_o(chk_int)
    );

    //── cfg_sec_resolution ───────────────────────────────────────
    wire [5:0]  elem_w, epf, epc, rem_e;
    wire [15:0] total_e;
    wire [3:0]  act_cime, c_mask;
    wire [2:0]  addr_pat;
    wire [3:0]  precision;
    wire        mx_en, psum_en;
    wire [13:0] dim0_xf, dim0_xf_out;
    wire [12:0] dim1_xf, dim1_xf_out;

    cfg_sec_resolution u_resolve (
        .cfg_dim0_in_i(cfg_size_dim0_in_i),.cfg_dim0_out_i(cfg_size_dim0_out_i),
        .cfg_dim1_in_i(cfg_size_dim1_in_i),.cfg_dim1_out_i(cfg_size_dim1_out_i),
        .cfg_stride_in_i(cfg_stride_dim1_in_i),.cfg_stride_out_i(cfg_stride_dim1_out_i),
        .dim0_xfer_o(dim0_xf), .dim1_xfer_o(dim1_xf),  // 32B→64B converted
        .cfg_width_in_i(cfg_width_in_i),.cfg_width_wt_i(cfg_width_wt_i),
        .cfg_width_out_i(cfg_width_out_i),
        .cfg_type_in_i(cfg_type_in_i),.cfg_type_wt_i(cfg_type_wt_i),
        .cfg_type_out_i(cfg_type_out_i),.cfg_acc_en_i(cfg_acc_en_i),
        .cfg_mx_in_i(cfg_mx_in_i),.cfg_pattern_i(cfg_pattern_i),
        .cfg_task_i(cfg_task_select_i),
        .elem_width_o(elem_w),.elems_per_xfer_o(epf),.total_elems_o(total_e),
        .active_cime_o(act_cime),.cime_mask_o(c_mask),
        .elems_per_cime_o(epc),.rem_elems_o(rem_e),
        .addr_pattern_o(addr_pat),.precision_o(precision),
        .mx_en_o(mx_en),.psum_en_o(psum_en)
    );

    //── cfg_ctrl ─────────────────────────────────────────────────
    wire [2:0] fsm_state;
    wire       ctrl_done, ctrl_error;

    cfg_ctrl u_cfg_ctrl (
        .clk_i(clk_i),.rst_n(rst_n),.start_i(start_i),
        .chk_pass_i(chk_pass),.chk_errors_i(chk_int),
        .base_out_i(cfg_base_out_i),.base_in_i(cfg_base_in_i),
        .base_orig_i(cfg_base_orig_i),.base_wt_i(cfg_base_wt_i),
        .base_mx_i(cfg_base_mx_i),
        .dim0_out_i({1'b0, dim0_xf[13:1]}),.dim0_in_i({1'b0, dim0_xf[13:1]}),  // 64B transfer count
        .dim1_out_i({1'b0, dim1_xf[12:1]}),.dim1_in_i({1'b0, dim1_xf[12:1]}),
        .stride_out_i(cfg_stride_dim1_out_i),.stride_in_i(cfg_stride_dim1_in_i),
        .precision_i(precision),.task_i(cfg_task_select_i),
        .active_cime_i(act_cime),
        .elem_width_i(elem_w),.elems_per_xfer_i(epf),.elems_per_cime_i(epc),
        .rem_elems_i(rem_e),.total_elems_i(total_e),
        .cime_mask_i(c_mask),.addr_pattern_i(addr_pat),
        .rd0_start_o(ctrl_rd0_start_o),.rd1_start_o(ctrl_rd1_start_o),
        .rd0_base_o(ctrl_rd0_base_o),.rd1_base_o(ctrl_rd1_base_o),
        .rd0_dim0_o(ctrl_rd0_dim0_o),.rd1_dim0_o(ctrl_rd1_dim0_o),
        .rd0_dim1_o(ctrl_rd0_dim1_o),.rd1_dim1_o(ctrl_rd1_dim1_o),
        .rd0_stride_o(ctrl_rd0_stride_o),.rd1_stride_o(ctrl_rd1_stride_o),
        .precision_o(ctrl_precision_o),.mx_en_o(ctrl_mx_en_o),.psum_en_o(ctrl_psum_en_o),
        .active_cime_o(ctrl_active_cime_o),.cime_mask_o(ctrl_cime_mask_o),
        .addr_pattern_o(ctrl_addr_pattern_o),
        .elems_per_xfer_o(ctrl_elems_per_xfer_o),.elems_per_cime_o(ctrl_elems_per_cime_o),
        .rem_elems_o(ctrl_rem_elems_o),.total_elems_o(ctrl_total_elems_o),
        .state_o(fsm_state),.done_o(ctrl_done),.error_o(ctrl_error)
    );

    //── lp_ctrl ──────────────────────────────────────────────────
    lp_ctrl u_lp (
        .clk_i(clk_i),.rst_n(rst_n),.fsm_state_i(fsm_state),
        .psum_en_i(psum_en),.mx_en_i(mx_en),.cime_mask_i(c_mask),
        .pattern_i(cfg_pattern_i),.active_cime_i(act_cime),
        .cg_rd0_en_o(),.cg_rd1_en_o(),.cg_mx_en_o(),
        .cg_cime_en_o(),.cg_post_en_o(),.cg_wr_en_o(),.cg_storage_en_o(),
        .lp_sleep_o()
    );

    //── state_report ─────────────────────────────────────────────
    //── shape_analyzer ──────────────────────────────────────────
    wire [1:0]  grid_rows, grid_cols;
    wire [9:0]  cime_in_w, cime_wt_w;
    wire [5:0]  rows_per_c, elems_per_r;
    wire [13:0] dim0_cols;

    shape_analyzer u_shape (
        .pattern_i     (cfg_pattern_i),
        .dim0_in_i     (cfg_size_dim0_in_i),
        .dim0_out_i    (cfg_size_dim0_out_i),
        .width_in_i    (cfg_width_in_i),
        .width_wt_i    (cfg_width_wt_i),
        .width_out_i   (cfg_width_out_i),
        .grid_rows_o   (grid_rows),    .grid_cols_o   (grid_cols),
        .active_cime_o (ctrl_active_cime_o),  // override sec_resolution
        .cime_in_width_o(cime_in_w),   .cime_wt_width_o(cime_wt_w),
        .rows_per_cime_o(rows_per_c),  .elems_per_row_o(elems_per_r),
        .dim0_cols_o   (dim0_cols)
    );
    assign ctrl_grid_rows_o    = grid_rows;
    assign ctrl_grid_cols_o    = grid_cols;
    assign ctrl_cime_in_width_o = cime_in_w;
    assign ctrl_cime_wt_width_o = cime_wt_w;
    assign ctrl_rows_per_cime_o = rows_per_c;
    assign ctrl_elems_per_row_o = elems_per_r;
    assign ctrl_dim0_cols_o     = dim0_cols;

    //── state_report ─────────────────────────────────────────────
    state_report u_report (
        .clk_i(clk_i),.rst_n(rst_n),.fsm_state_i(fsm_state),
        .chk_error_i(chk_int),.done_i(ctrl_done),
        .compute_error_i(1'b0),
        .perf_wr_i(perf_wr_i),.perf_rd0_i(perf_rd0_i),.perf_rd1_i(perf_rd1_i),
        .perf_cycle_i(perf_cycle_i),.perf_cim_i(perf_cim_i),.perf_fp_i(perf_fp_busy_i),
        .perf_en_i(perf_en_i),.perf_start_i(perf_start_i),.perf_pause_i(perf_pause_i),
        .perf_continue_i(perf_continue_i),.perf_end_i(perf_end_i),
        .int_o(int_o),.perf_cnt_reg_o(perf_cnt_reg_o),
        .dbg_reg0_o(dbg_reg0_o),.dbg_reg1_o(dbg_reg1_o),.dbg_reg2_o(dbg_reg2_o),
        .done_pulse_o(done_o)
    );

    assign done_lclrd_o = 1'b0;

endmodule
