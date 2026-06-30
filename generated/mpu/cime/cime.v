//==============================================================================
// CIME — CIM Engine: 2× CIMM + INT37→INT38 + EXP comparison (6 scenarios)
//
// Key CIME operation per flow chart: 累加时与另外通道的EXP比较
//   Scenario 1 (INT×INT): EXP=0, passthrough INT37→INT38
//   Scenario 2 (INT×FP):  CIMM EXP,  CIME EXP比较→shift→INT38
//   Scenario 3 (FP×INT):  CIMM 9b EXP, CIME EXP比较→shift→INT38 (7-step restore)
//   Scenario 4 (FP×FP):   CIMM EXP相加→9b, TMU EXP, CIME EXP比较→INT38
//   Scenario 5 (MX×MX):   CIMM EXP相加+share, CIME EXP比较→INT38
//   Scenario 6 (FP×MX):   CIMM EXP相加+share, CIME EXP比较→INT38
//==============================================================================
module cime #(parameter CIMM_PER_CIME = 2) (
    input  wire         storage_clk, compute_clk, allon_clk, rst_n,
    input  wire [CIMM_PER_CIME-1:0]         cimm_wen, cimm_ren_global, cimm_ren_local, cimm_cen,
    input  wire [10:0]                      cfg_fmt,
    input  wire [63:0]                      mask_en,
    input  wire [CIMM_PER_CIME-1:0][9:0]    cimm_addr,
    input  wire [CIMM_PER_CIME-1:0][255:0]  cimm_mem_d,
    input  wire [511:0]                     i_data,
    input  wire [8:0]                       exp,
    input  wire [7:0]                       share_exp,
    output wire [CIMM_PER_CIME-1:0][255:0]  cimm_mem_q,
    output wire [CIMM_PER_CIME-1:0][591:0]  cimm_o_manti,
    output wire [CIMM_PER_CIME-1:0][143:0]  cimm_o_exp,
    output wire [CIMM_PER_CIME-1:0]         cimm_o_data_flag,
    output reg  [38:0]                      int38_result_o,
    output reg  [7:0]                       int38_exp_o,
    output reg                              int38_valid_o,
    input  wire                             dft_bist_mode, dft_bist_start,
    input  wire                             dft_mbist_en, dft_lbist_en, dft_alg_sel,
    output wire [CIMM_PER_CIME-1:0]         dft_alg_end, dft_mcomp_go, dft_lcomp_go,
    input  wire [26:0]                      creg_dcim_ema
);
    genvar gi;
    generate for (gi = 0; gi < CIMM_PER_CIME; gi = gi + 1) begin : cimm_gen
        cimm u_cimm (.storage_clk(storage_clk),.compute_clk(compute_clk),.allon_clk(allon_clk),.rst_n(rst_n),
            .wen(cimm_wen[gi]),.ren_global(cimm_ren_global[gi]),.ren_local(cimm_ren_local[gi]),.cen(cimm_cen[gi]),
            .cfg_fmt(cfg_fmt),.mask_en(mask_en),.addr(cimm_addr[gi]),.mem_d(cimm_mem_d[gi]),.i_data(i_data),
            .exp(exp),.share_exp(share_exp),.mem_q(cimm_mem_q[gi]),.o_manti(cimm_o_manti[gi]),
            .o_exp(cimm_o_exp[gi]),.o_data_flag(cimm_o_data_flag[gi]),.creg_dcim_ema(creg_dcim_ema),
            .dft_bist_mode(dft_bist_mode),.dft_bist_start(dft_bist_start),.dft_mbist_en(dft_mbist_en),
            .dft_lbist_en(dft_lbist_en),.dft_alg_sel(dft_alg_sel),.dft_ram_cen(),.dft_ram_wen(),
            .dft_ram_addr(),.dft_ram_q(512'd0),.dft_alg_end(dft_alg_end[gi]),.dft_atpg_end(),
            .dft_lcomp_go(dft_lcomp_go[gi]),.dft_mcomp_go(dft_mcomp_go[gi]));
    end endgenerate

    //── CIME间累加: EXP比较 + 移位 + INT37+INT37→INT38 ────────
    reg [36:0] int37_a, int37_b;
    reg [7:0]  exp_a, exp_b;
    reg        pending;

    always @(posedge compute_clk or negedge rst_n) begin
        if (!rst_n) begin
            int37_a<=37'd0; int37_b<=37'd0; exp_a<=8'd0; exp_b<=8'd0;
            pending<=0; int38_result_o<=39'd0; int38_exp_o<=8'd0; int38_valid_o<=0;
        end else if (cimm_o_data_flag[0] && !pending) begin
            int37_a<=cimm_o_manti[0][36:0]; exp_a<=cimm_o_exp[0][7:0]; pending<=1; int38_valid_o<=0;
        end else if (cimm_o_data_flag[1] && pending) begin
            int37_b<=cimm_o_manti[1][36:0]; exp_b<=cimm_o_exp[1][7:0];
            // EXP比较: 累加时与另外通道的EXP比较
            if (exp_a > exp_b) begin
                int38_result_o <= {2'b0,int37_a} + ({2'b0,int37_b}>>(exp_a-exp_b));
                int38_exp_o <= exp_a;
            end else begin
                int38_result_o <= {2'b0,int37_b} + ({2'b0,int37_a}>>(exp_b-exp_a));
                int38_exp_o <= exp_b;
            end
            int38_valid_o<=1; pending<=0;
        end else int38_valid_o<=0;
    end
endmodule
