//==============================================================================
// state_report — State Reporting & Interrupt Generation (32-bit)
// Reports to COMMAND SCHEDULAR: done, error, perf counters, debug signals
// Interrupt map per spec §10.1.1 (mpu_creg_int[31:0])
//==============================================================================
module state_report (
    input  wire         clk_i,
    input  wire         rst_n,
    input  wire [2:0]   fsm_state_i,
    input  wire [31:0]  chk_error_i,       // full int[31:0] from cfg_chk
    input  wire         done_i,            // from wr_channel
    input  wire         compute_error_i,   // NaN/Inf/overflow from CIME/POST
    input  wire [31:0]  perf_wr_i,         // write count
    input  wire [31:0]  perf_rd0_i,        // RD0 read count
    input  wire [31:0]  perf_rd1_i,        // RD1 read count
    input  wire [31:0]  perf_cycle_i,      // cycle count
    input  wire [31:0]  perf_cim_i,        // CIM access count
    input  wire [31:0]  perf_fp_i,         // FP busy cycle count

    //── Perf control ─────────────────────────────────────────────
    input  wire         perf_en_i,
    input  wire         perf_start_i, perf_pause_i,
    input  wire         perf_continue_i, perf_end_i,

    //── Outputs ──────────────────────────────────────────────────
    output reg  [31:0]  int_o,             // interrupt status
    output reg  [191:0] perf_cnt_reg_o,    // performance counter reg
    output reg  [31:0]  dbg_reg0_o,        // debug register 0
    output reg  [31:0]  dbg_reg1_o,
    output reg  [31:0]  dbg_reg2_o,
    output reg          done_pulse_o       // to COMMAND SCHEDULAR
);

    //── Interrupt generation per spec §10.1.1 ────────────────────
    // Config errors [31:4] come from cfg_chk (combinational int_o)
    // Compute errors [3:0] come from pipeline modules
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            int_o         <= 32'd0;
            done_pulse_o  <= 1'b0;
        end else begin
            // Config errors: latch cfg_chk output at CFG_CHK state
            if (fsm_state_i == `MPU_ERROR)
                int_o[31:4] <= chk_error_i[31:4];  // pass through full 32b from cfg_chk

            // Compute errors [3:0] (from pipeline)
            if (compute_error_i)
                int_o[3:0] <= 4'b1111;   // [3]=Inf [2]=NaN [1]=underflow [0]=overflow

            // Done: clear on completion
            if (fsm_state_i == `MPU_DONE) begin
                done_pulse_o <= 1'b1;
                int_o        <= 32'd0;
            end else begin
                done_pulse_o <= 1'b0;
            end
        end
    end

    //── Performance counters ─────────────────────────────────────
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            perf_cnt_reg_o <= 192'd0;
        end else if (fsm_state_i == `MPU_DONE && perf_en_i) begin
            perf_cnt_reg_o[191:160] <= perf_wr_i;      // write channel count
            perf_cnt_reg_o[159:128] <= perf_rd1_i;     // RD1 read count
            perf_cnt_reg_o[127:96]  <= perf_rd0_i;     // RD0 read count
            perf_cnt_reg_o[95:64]   <= perf_cycle_i;   // compute cycle count
            perf_cnt_reg_o[63:32]   <= perf_cim_i;     // CIM access count
            perf_cnt_reg_o[31:0]    <= perf_fp_i;      // FP-CIM busy cycles
        end
    end

endmodule
