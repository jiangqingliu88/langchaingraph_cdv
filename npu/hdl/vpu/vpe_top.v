//==============================================================================
// vpe_top — 16× Vector Processing Engine Array
// Supports VV_V, VS_V, V_V, V_S instruction modes
//==============================================================================
`include "vpu_defines.vh"

module vpe_top #(
    parameter VPE_NUM = 16
) (
    input  wire                     clk_i,
    input  wire                     rst_n,

    // Config
    input  wire [5:0]               cfg_op,
    input  wire [1:0]               cfg_funct_sel,
    input  wire                     cfg_satu,
    input  wire                     cfg_dis0,
    input  wire [2:0]               cfg_rm,
    input  wire [2:0]               cfg_type_in1,
    input  wire [2:0]               cfg_type_in2,
    input  wire [2:0]               cfg_type_out,

    // Data in (16 lanes × 32-bit elements)
    input  wire [VPE_NUM-1:0][31:0] vec0_elem_i,
    input  wire [VPE_NUM-1:0][31:0] vec1_elem_i,
    input  wire [VPE_NUM-1:0][7:0]  vec0_exp_i,
    input  wire [VPE_NUM-1:0][7:0]  vec1_exp_i,
    input  wire [3:0]               active_vpe_i,    // # active VPEs: 1-16
    input  wire                     valid_i,

    // Data out
    output wire [VPE_NUM-1:0][31:0] result_o,
    output wire [VPE_NUM-1:0]       result_valid_o,
    output wire                     done_o
);

    //── V_S (reduce) accumulator chain ────────────────────────────
    wire [VPE_NUM:0][31:0]          reduce_chain;     // reduce_chain[0] = init
    wire [VPE_NUM:0][7:0]           reduce_exp_chain;
    wire [VPE_NUM:0]                reduce_valid;

    assign reduce_chain[0]   = 32'd0;
    assign reduce_exp_chain[0] = 8'd0;
    assign reduce_valid[0]   = 1'b1;

    genvar i;
    generate
    for (i = 0; i < VPE_NUM; i = i + 1) begin : vpe_gen

        //── Per-VPE operation ────────────────────────────────────
        wire [31:0] vpe_result;
        wire        vpe_valid;

        vpe u_vpe (
            .clk_i         (clk_i),
            .rst_n         (rst_n),
            .cfg_op        (cfg_op),
            .cfg_funct_sel (cfg_funct_sel),
            .cfg_satu      (cfg_satu),
            .cfg_dis0      (cfg_dis0),
            .cfg_rm        (cfg_rm),
            .cfg_type_in1  (cfg_type_in1),
            .cfg_type_in2  (cfg_type_in2),
            .cfg_type_out  (cfg_type_out),
            .vec0_elem_i   (vec0_elem_i[i]),
            .vec1_elem_i   (vec1_elem_i[i]),
            .vec0_exp_i    (vec0_exp_i[i]),
            .vec1_exp_i    (vec1_exp_i[i]),
            .vpe_en        (valid_i && (i < active_vpe_i)),
            // V_S reduce chain
            .reduce_prev_i      (reduce_chain[i]),
            .reduce_prev_exp_i  (reduce_exp_chain[i]),
            .reduce_prev_valid_i(reduce_valid[i]),
            .reduce_next_o      (reduce_chain[i+1]),
            .reduce_next_exp_o  (reduce_exp_chain[i+1]),
            .reduce_next_valid_o(reduce_valid[i+1]),
            // Output
            .result_o       (vpe_result),
            .result_valid_o (vpe_valid)
        );

        assign result_o[i]      = vpe_result;
        assign result_valid_o[i] = vpe_valid;

    end
    endgenerate

    //── Done: when all active VPEs have produced results ──────────
    // Simple done detection: last VPE lane valid
    reg  done_r;
    wire all_active_done;
    assign all_active_done = &(result_valid_o | ~({{VPE_NUM-1{1'b0}}, 1'b1} << active_vpe_i));

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n)
            done_r <= 1'b0;
        else if (valid_i && all_active_done)
            done_r <= 1'b1;
        else if (done_r)
            done_r <= 1'b0;
    end
    assign done_o = done_r;

endmodule
