//==============================================================================
// VPU Top-Level Module — Vector Processing Unit
// Based on vpu.md spec v2.2: 16×VPE, 512-bit datapath, RV32 config interface
//==============================================================================
`include "vpu_defines.vh"

module vpu_top #(
    parameter RV_LEN        = 32,
    parameter LMEM_WD       = 512,
    parameter LMEM_ADDR_WD  = 32,
    parameter VPE_NUM       = 16
) (
    // Clock & Reset
    input  wire                     clk_i,
    input  wire                     rst_n,

    //── Configuration Signals ────────────────────────────────────
    // Output (Vector O)
    input  wire [1:0]               cfg_type_out,
    input  wire [2:0]               cfg_wd_out,
    input  wire [1:0]               cfg_exp_wd_out,
    // Input 1 (Vector 0 / Operand A)
    input  wire [2:0]               cfg_type_in1,
    input  wire [2:0]               cfg_wd_in1,
    input  wire [1:0]               cfg_exp_wd_in1,
    // Input 2 (Vector 1 / Operand B)
    input  wire [2:0]               cfg_type_in2,
    input  wire [2:0]               cfg_wd_in2,
    // Dimension sizes
    input  wire [15:0]              cfg_size_dim0_in1,
    input  wire [4:0]               cfg_rem_dim0_in1,
    input  wire [15:0]              cfg_size_dim0_in2,
    input  wire [4:0]               cfg_rem_dim0_in2,
    input  wire [15:0]              cfg_size_dim0_out,
    input  wire [4:0]               cfg_rem_dim0_out,
    // Operation & control
    input  wire [5:0]               cfg_op,
    input  wire [1:0]               cfg_funct_sel,   // VV_V/VS_V/V_S/V_V
    input  wire                     cfg_satu,        // saturate
    input  wire                     cfg_dis0,        // denorm→0
    input  wire [2:0]               cfg_rm,          // rounding mode
    input  wire                     cfg_bypass,      // bypass vector1

    // Base addresses
    input  wire [LMEM_ADDR_WD-1:0]  byte_base_out,
    input  wire                     byte_base_out_vld,
    input  wire [LMEM_ADDR_WD-1:0]  byte_base_in1,
    input  wire                     byte_base_in1_vld,
    input  wire [LMEM_ADDR_WD-1:0]  byte_base_in2,
    // Scalar data for VS_V
    input  wire [RV_LEN-1:0]        scalar_data_in2,
    output wire [31:0]              scalar_data_o,

    // Start / Done
    input  wire                     start_i,
    output wire                     done_o,

    //── Write Channel ch0_wr ─────────────────────────────────────
    output wire [LMEM_ADDR_WD-1:0]  ch0_wr_req_addr_o,
    output wire [LMEM_WD-1:0]       ch0_wr_req_data_o,
    output wire                     ch0_wr_req_flag_o,
    output wire                     ch0_wr_req_valid_o,
    output wire                     ch0_wr_exp_valid_o,
    input  wire                     ch0_wr_req_ready_i,
    input  wire                     ch0_wr_ack_valid_i,
    output wire [1:0]               ch0_wr_req_strobe_o,
    output wire                     ch0_wr_ack_ready_o,

    //── Read Channel ch1_rd (Vector 0) ───────────────────────────
    output wire [LMEM_ADDR_WD-1:0]  ch1_rd_req_addr_o,
    output wire                     ch1_rd_req_valid_o,
    input  wire                     ch1_rd_req_ready_i,
    input  wire                     ch1_rd_exp_valid_i,
    input  wire [LMEM_WD-1:0]       ch1_rd_ack_data_i,
    input  wire                     ch1_rd_ack_valid_i,
    output wire                     ch1_rd_ack_ready_o,

    //── Read Channel ch2_rd (Vector 1) ───────────────────────────
    output wire [LMEM_ADDR_WD-1:0]  ch2_rd_req_addr_o,
    output wire                     ch2_rd_req_valid_o,
    input  wire                     ch2_rd_req_ready_i,
    input  wire [LMEM_WD-1:0]       ch2_rd_ack_data_i,
    input  wire                     ch2_rd_ack_valid_i,
    output wire                     ch2_rd_ack_ready_o
);

    //══════════════════════════════════════════════════════════════
    // Wires between sub-modules
    //══════════════════════════════════════════════════════════════

    // data_top → vpe_top : aligned vector elements
    wire [VPE_NUM-1:0][31:0]        dt2vpe_vec0_elem;
    wire [VPE_NUM-1:0][31:0]        dt2vpe_vec1_elem;
    wire [VPE_NUM-1:0][7:0]         dt2vpe_vec0_exp;
    wire [VPE_NUM-1:0][7:0]         dt2vpe_vec1_exp;
    wire [3:0]                      dt2vpe_active_vpe;   // how many VPEs active (1-16)
    wire                            dt2vpe_valid;

    // vpe_top → data_top : results
    wire [VPE_NUM-1:0][31:0]        vpe2dt_result;
    wire [VPE_NUM-1:0]              vpe2dt_valid;
    wire                            vpe2dt_done;

    // Config bus to data_top
    wire                            cfg_bypass;
    wire [2:0]                      cfg_type_out, cfg_wd_out;
    wire [1:0]                      cfg_exp_wd_out;
    wire [2:0]                      cfg_type_in1, cfg_wd_in1;
    wire [2:0]                      cfg_type_in2, cfg_wd_in2;
    wire [1:0]                      cfg_exp_wd_in1;

    //══════════════════════════════════════════════════════════════
    // Sub-module: data_top — fetch, align, dispatch, writeback
    //══════════════════════════════════════════════════════════════
    data_top #(
        .LMEM_WD       (LMEM_WD),
        .LMEM_ADDR_WD  (LMEM_ADDR_WD),
        .VPE_NUM       (VPE_NUM),
        .RV_LEN        (RV_LEN)
    ) u_data_top (
        .clk_i             (clk_i),
        .rst_n             (rst_n),
        // Config
        .cfg_type_out      (cfg_type_out),
        .cfg_wd_out        (cfg_wd_out),
        .cfg_exp_wd_out    (cfg_exp_wd_out),
        .cfg_type_in1      (cfg_type_in1),
        .cfg_wd_in1        (cfg_wd_in1),
        .cfg_exp_wd_in1    (cfg_exp_wd_in1),
        .cfg_type_in2      (cfg_type_in2),
        .cfg_wd_in2        (cfg_wd_in2),
        .cfg_size_dim0_in1 (cfg_size_dim0_in1),
        .cfg_rem_dim0_in1  (cfg_rem_dim0_in1),
        .cfg_size_dim0_in2 (cfg_size_dim0_in2),
        .cfg_rem_dim0_in2  (cfg_rem_dim0_in2),
        .cfg_size_dim0_out (cfg_size_dim0_out),
        .cfg_rem_dim0_out  (cfg_rem_dim0_out),
        .cfg_op            (cfg_op),
        .cfg_funct_sel     (cfg_funct_sel),
        .cfg_bypass        (cfg_bypass),
        .byte_base_out     (byte_base_out),
        .byte_base_out_vld (byte_base_out_vld),
        .byte_base_in1     (byte_base_in1),
        .byte_base_in1_vld (byte_base_in1_vld),
        .byte_base_in2     (byte_base_in2),
        .scalar_data_in2   (scalar_data_in2),
        .scalar_data_o     (scalar_data_o),
        .start_i           (start_i),
        .done_o            (done_o),
        // Write channel
        .ch0_wr_req_addr_o (ch0_wr_req_addr_o),
        .ch0_wr_req_data_o (ch0_wr_req_data_o),
        .ch0_wr_req_flag_o (ch0_wr_req_flag_o),
        .ch0_wr_req_valid_o(ch0_wr_req_valid_o),
        .ch0_wr_exp_valid_o(ch0_wr_exp_valid_o),
        .ch0_wr_req_ready_i(ch0_wr_req_ready_i),
        .ch0_wr_ack_valid_i(ch0_wr_ack_valid_i),
        .ch0_wr_req_strobe_o(ch0_wr_req_strobe_o),
        .ch0_wr_ack_ready_o(ch0_wr_ack_ready_o),
        // Read ch1
        .ch1_rd_req_addr_o (ch1_rd_req_addr_o),
        .ch1_rd_req_valid_o(ch1_rd_req_valid_o),
        .ch1_rd_req_ready_i(ch1_rd_req_ready_i),
        .ch1_rd_exp_valid_i(ch1_rd_exp_valid_i),
        .ch1_rd_ack_data_i (ch1_rd_ack_data_i),
        .ch1_rd_ack_valid_i(ch1_rd_ack_valid_i),
        .ch1_rd_ack_ready_o(ch1_rd_ack_ready_o),
        // Read ch2
        .ch2_rd_req_addr_o (ch2_rd_req_addr_o),
        .ch2_rd_req_valid_o(ch2_rd_req_valid_o),
        .ch2_rd_req_ready_i(ch2_rd_req_ready_i),
        .ch2_rd_ack_data_i (ch2_rd_ack_data_i),
        .ch2_rd_ack_valid_i(ch2_rd_ack_valid_i),
        .ch2_rd_ack_ready_o(ch2_rd_ack_ready_o),
        // to vpe_top
        .vec0_elem_o       (dt2vpe_vec0_elem),
        .vec1_elem_o       (dt2vpe_vec1_elem),
        .vec0_exp_o        (dt2vpe_vec0_exp),
        .vec1_exp_o        (dt2vpe_vec1_exp),
        .active_vpe_o      (dt2vpe_active_vpe),
        .dispatch_valid_o  (dt2vpe_valid),
        // from vpe_top
        .result_i          (vpe2dt_result),
        .result_valid_i    (vpe2dt_valid),
        .vpe_done_i        (vpe2dt_done)
    );

    //══════════════════════════════════════════════════════════════
    // Sub-module: vpe_top — 16× Vector Processing Engines
    //══════════════════════════════════════════════════════════════
    vpe_top #(
        .VPE_NUM (VPE_NUM)
    ) u_vpe_top (
        .clk_i           (clk_i),
        .rst_n           (rst_n),
        .cfg_op          (cfg_op),
        .cfg_funct_sel   (cfg_funct_sel),
        .cfg_satu        (cfg_satu),
        .cfg_dis0        (cfg_dis0),
        .cfg_rm          (cfg_rm),
        .cfg_type_in1    (cfg_type_in1),
        .cfg_type_in2    (cfg_type_in2),
        .cfg_type_out    (cfg_type_out),
        // Data in
        .vec0_elem_i     (dt2vpe_vec0_elem),
        .vec1_elem_i     (dt2vpe_vec1_elem),
        .vec0_exp_i      (dt2vpe_vec0_exp),
        .vec1_exp_i      (dt2vpe_vec1_exp),
        .active_vpe_i    (dt2vpe_active_vpe),
        .valid_i         (dt2vpe_valid),
        // Data out
        .result_o        (vpe2dt_result),
        .result_valid_o  (vpe2dt_valid),
        .done_o          (vpe2dt_done)
    );

endmodule
