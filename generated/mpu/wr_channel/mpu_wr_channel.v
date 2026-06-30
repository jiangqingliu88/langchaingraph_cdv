//==============================================================================
// MPU_WR_CHANNEL — Write results to SPAD via XBAR
// Address generator for output, flag on last transfer, done pulse
//==============================================================================
`include "mpu_defines.vh"

module mpu_wr_channel #(
    parameter P_IO_DATA_WD   = 512,
    parameter P_ADDR_WIDTH   = 32
) (
    input  wire         clk_i,
    input  wire         rst_n,

    //── From POST_PROCESS ─────────────────────────────────────────
    input  wire [P_IO_DATA_WD-1:0] wr_data_i,
    input  wire                     wr_valid_i,
    output wire                     wr_ready_o,
    input  wire                     wr_last_i,

    //── XBAR Write ────────────────────────────────────────────────
    output reg  [P_ADDR_WIDTH-1:0]  wr_req_addr_o,
    output reg  [P_IO_DATA_WD-1:0]  wr_req_data_o,
    output reg                      wr_req_flag_o,
    output reg  [1:0]               wr_req_strobe_o,
    output reg                      wr_req_vld_o,
    input  wire                     wr_req_rdy_i,
    input  wire                     wr_rsp_vld_i,
    output reg                      wr_rsp_rdy_o,

    //── Config ────────────────────────────────────────────────────
    input  wire [31:0]              base_addr_i,
    input  wire [13:0]              dim0_size_i,
    input  wire [12:0]              dim1_size_i,
    input  wire [12:0]              stride_i,
    input  wire [2:0]               pattern_i,

    //── Done ──────────────────────────────────────────────────────
    output reg                      done_pulse_o,

    //── Perf ──────────────────────────────────────────────────────
    output reg  [31:0]              perf_wr_cnt_o
);

    //══════════════════════════════════════════════════════════════
    // Address Generator (type0: linear sequential)
    //══════════════════════════════════════════════════════════════
    reg [31:0] wr_cur_addr;
    reg [13:0] wr_dim0_cnt;
    reg [12:0] wr_dim1_cnt;
    reg        wr_active;

    // Handshake with post_process
    assign wr_ready_o = !wr_active || (wr_req_vld_o && wr_req_rdy_i);

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            wr_cur_addr    <= 32'd0;
            wr_dim0_cnt    <= 14'd0;
            wr_dim1_cnt    <= 13'd0;
            wr_active      <= 1'b0;
            wr_req_addr_o  <= 32'd0;
            wr_req_data_o  <= 'd0;
            wr_req_flag_o  <= 1'b0;
            wr_req_strobe_o<= 2'b11;  // full 512-bit valid
            wr_req_vld_o   <= 1'b0;
            wr_rsp_rdy_o   <= 1'b1;   // always ready for ack
            done_pulse_o   <= 1'b0;
        end else begin
            done_pulse_o <= 1'b0;

            if (wr_valid_i && wr_ready_o) begin
                // Accept data from post_process
                wr_req_addr_o <= wr_cur_addr;
                wr_req_data_o <= wr_data_i;
                wr_req_strobe_o <= 2'b11;
                wr_req_vld_o  <= 1'b1;
                wr_active     <= 1'b1;

                // Determine flag (last)
                if (wr_last_i) begin
                    wr_req_flag_o <= 1'b1;
                end else begin
                    wr_req_flag_o <= 1'b0;
                end
            end else if (wr_req_vld_o && wr_req_rdy_i) begin
                // Write accepted by XBAR
                wr_req_vld_o <= 1'b0;

                // Update address
                wr_cur_addr <= wr_cur_addr + 32'd64;  // 512-bit = 64 bytes

                // Update dimension counters
                if (wr_dim0_cnt >= dim0_size_i - 14'd1) begin
                    wr_dim0_cnt <= 14'd0;
                    if (wr_dim1_cnt >= dim1_size_i - 13'd1) begin
                        wr_dim1_cnt <= 13'd0;
                        wr_active   <= 1'b0;  // all done
                    end else begin
                        wr_dim1_cnt <= wr_dim1_cnt + 13'd1;
                        // Add stride for dim1
                        wr_cur_addr <= wr_cur_addr + {19'd0, stride_i} * 32'd64;
                    end
                end else begin
                    wr_dim0_cnt <= wr_dim0_cnt + 14'd1;
                end
            end

            // Done: last write ack received
            if (wr_rsp_vld_i && wr_rsp_rdy_o) begin
                if (wr_req_flag_o) begin
                    done_pulse_o <= 1'b1;
                end
            end
        end
    end

    //── Perf counter ──────────────────────────────────────────────
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n)
            perf_wr_cnt_o <= 32'd0;
        else if (wr_req_vld_o && wr_req_rdy_i)
            perf_wr_cnt_o <= perf_wr_cnt_o + 32'd2;  // 512-bit = 2×256-bit
    end

endmodule
