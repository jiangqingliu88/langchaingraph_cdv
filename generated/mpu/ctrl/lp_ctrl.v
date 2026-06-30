//==============================================================================
// lp_ctrl — Low Power Control
// Clock gating & power management for MPU sub-modules.
// Three LP sources:
//   1. Task-level: COMMAND SCHEDULAR gates compute_clk between tasks
//   2. Config-level: per-feature clock gating (PSUM, MX, unused CIMEs)
//   3. Data-level: CIMM clock gate on backpressure for data integrity
//==============================================================================
module lp_ctrl (
    input  wire         clk_i,
    input  wire         rst_n,
    input  wire [2:0]   fsm_state_i,       // from cfg_ctrl
    input  wire         psum_en_i,          // PSUM feature enable
    input  wire         mx_en_i,            // MX feature enable
    input  wire [3:0]   cime_mask_i,        // active CIME mask
    input  wire [2:0]   pattern_i,
    input  wire [3:0]   active_cime_i,

    //── Clock gate enables ───────────────────────────────────────
    output reg          cg_rd0_en_o,        // RD0 clock gate
    output reg          cg_rd1_en_o,        // RD1 clock gate (PSUM)
    output reg          cg_mx_en_o,         // MX EXP clock gate
    output reg  [3:0]   cg_cime_en_o,       // per-CIME clock gate
    output reg          cg_post_en_o,       // post_process clock gate
    output reg          cg_wr_en_o,         // wr_channel clock gate
    output reg          cg_storage_en_o,    // storage domain clock gate
    output reg          lp_sleep_o          // global sleep indicator
);

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            cg_rd0_en_o    <= 1'b0;
            cg_rd1_en_o    <= 1'b0;
            cg_mx_en_o     <= 1'b0;
            cg_cime_en_o   <= 4'd0;
            cg_post_en_o   <= 1'b0;
            cg_wr_en_o     <= 1'b0;
            cg_storage_en_o<= 1'b1;  // storage always on for external access
            lp_sleep_o     <= 1'b1;
        end else begin
            // Task-level: only enable during RUN state
            if (fsm_state_i == `MPU_RUN) begin
                lp_sleep_o     <= 1'b0;
                cg_rd0_en_o    <= 1'b1;          // RD0 always active during compute
                cg_rd1_en_o    <= psum_en_i;      // RD1 only for PSUM
                cg_mx_en_o     <= mx_en_i;        // MX EXP only for MX mode
                cg_cime_en_o   <= cime_mask_i;    // only active CIMEs
                cg_post_en_o   <= 1'b1;
                cg_wr_en_o     <= 1'b1;
            end else begin
                lp_sleep_o     <= 1'b1;
                cg_rd0_en_o    <= 1'b0;
                cg_rd1_en_o    <= 1'b0;
                cg_mx_en_o     <= 1'b0;
                cg_cime_en_o   <= 4'd0;
                cg_post_en_o   <= 1'b0;
                cg_wr_en_o     <= 1'b0;
            end
            // Storage domain: always on for weight read/write by external masters
            cg_storage_en_o <= 1'b1;
        end
    end

endmodule
