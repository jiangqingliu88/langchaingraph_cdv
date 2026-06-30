//==============================================================================
// MPU_RD_CHANNEL — Read from SPAD, align, dispatch to CIMC
// RD0 = Activation (Input), RD1 = PSUM + MX-EXP
// Includes INPUT_ALIGN, FRR_DISPATCHER, SHAPING_REG
//==============================================================================
`include "mpu_defines.vh"

module mpu_rd_channel #(
    parameter P_IO_DATA_WD   = 512,
    parameter P_ADDR_WIDTH   = 32,
    parameter CIME_NUM       = 4
) (
    input  wire         clk_i,
    input  wire         rst_n,

    //── Control ───────────────────────────────────────────────────
    input  wire         rd0_start_i,
    input  wire         rd1_start_i,
    input  wire [31:0]  rd0_base_addr_i,
    input  wire [31:0]  rd1_base_addr_i,
    input  wire [13:0]  rd0_dim0_i,
    input  wire [13:0]  rd1_dim0_i,
    input  wire [12:0]  rd0_dim1_i,
    input  wire [12:0]  rd1_dim1_i,
    input  wire [12:0]  rd0_stride_i,
    input  wire [12:0]  rd1_stride_i,
    input  wire [3:0]   precision_i,   // {type, width[2:0]}
    input  wire         mx_en_i,
    input  wire         psum_en_i,
    input  wire [3:0]   active_cime_i,       // from ctrl shape parse
    input  wire [3:0]   cime_mask_i,
    input  wire [2:0]   addr_pattern_i,
    input  wire [5:0]   elems_per_xfer_i,

    //── XBAR Read Channel 0 (Activation) ──────────────────────────
    output reg  [P_ADDR_WIDTH-1:0]  rd0_req_addr_o,
    output reg                      rd0_req_vld_o,
    input  wire                     rd0_req_rdy_i,
    input  wire [P_IO_DATA_WD-1:0]  rd0_rsp_data_i,
    input  wire                     rd0_rsp_vld_i,
    output reg                      rd0_rsp_rdy_o,

    //── XBAR Read Channel 1 (PSUM + MX-EXP) ───────────────────────
    output reg  [P_ADDR_WIDTH-1:0]  rd1_req_addr_o,
    output reg                      rd1_req_vld_o,
    input  wire                     rd1_req_rdy_i,
    input  wire [P_IO_DATA_WD-1:0]  rd1_rsp_data_i,
    input  wire                     rd1_rsp_vld_i,
    output reg                      rd1_rsp_rdy_o,

    //── To CIMC (per-CIME data) ──────────────────────────────────
    output reg  [CIME_NUM-1:0][P_IO_DATA_WD-1:0] cim_data_o,
    output reg  [CIME_NUM-1:0][7:0]              cim_exp_o,
    output reg  [CIME_NUM-1:0]                   cim_valid_o,
    input  wire [CIME_NUM-1:0]                   cim_ready_i,

    //── Perf ──────────────────────────────────────────────────────
    output reg  [31:0]  perf_rd0_cnt_o,
    output reg  [31:0]  perf_rd1_cnt_o
);

    //══════════════════════════════════════════════════════════════
    // Address generators (per-channel)
    //══════════════════════════════════════════════════════════════
    reg [13:0] rd0_dim0_cnt, rd1_dim0_cnt;
    reg [12:0] rd0_dim1_cnt, rd1_dim1_cnt;
    reg [31:0] rd0_cur_addr, rd1_cur_addr;

    // Elem width extraction
    wire [2:0] wd_code   = precision_i[2:0];
    wire       is_fp     = precision_i[3];
    wire [4:0] elem_w    = get_elem_width(wd_code);
    wire [5:0] elems_per_xfer = 6'd64 / {1'b0, (elem_w >> 3)};  // elements per transfer

    //── RD0 Address Generator ────────────────────────────────────
    wire rd0_addr_gen_go = rd0_start_i && (rd0_dim1_cnt < rd0_dim1_i);
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            rd0_dim0_cnt   <= 14'd0;
            rd0_dim1_cnt   <= 13'd0;
            rd0_cur_addr   <= 32'd0;
        end else if (rd0_start_i) begin
            rd0_cur_addr <= rd0_base_addr_i;
            rd0_dim0_cnt <= 14'd0;
            rd0_dim1_cnt <= 13'd0;
        end else if (rd0_req_vld_o && rd0_req_rdy_i) begin
            // Increment address: 512-bit = 64 bytes per xfer
            rd0_cur_addr <= rd0_cur_addr + 32'd64;
            if (rd0_dim0_cnt >= rd0_dim0_i - 14'd1) begin
                rd0_dim0_cnt <= 14'd0;
                rd0_dim1_cnt <= rd0_dim1_cnt + 13'd1;
            end else begin
                rd0_dim0_cnt <= rd0_dim0_cnt + 14'd1;
            end
        end
    end

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            rd0_req_addr_o <= 32'd0;
            rd0_req_vld_o  <= 1'b0;
        end else if (rd0_addr_gen_go && !rd0_req_vld_o) begin
            rd0_req_addr_o <= rd0_cur_addr;
            rd0_req_vld_o  <= 1'b1;
        end else if (rd0_req_rdy_i) begin
            rd0_req_vld_o  <= 1'b0;
        end
    end

    //── RD1 Address Generator (shared: PSUM + MX-EXP) ────────────
    wire rd1_addr_gen_go = rd1_start_i && psum_en_i;
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            rd1_dim0_cnt   <= 14'd0;
            rd1_dim1_cnt   <= 13'd0;
            rd1_cur_addr   <= 32'd0;
        end else if (rd1_start_i) begin
            rd1_cur_addr <= rd1_base_addr_i;
            rd1_dim0_cnt <= 14'd0;
            rd1_dim1_cnt <= 13'd0;
        end else if (rd1_req_vld_o && rd1_req_rdy_i) begin
            rd1_cur_addr <= rd1_cur_addr + 32'd64;
            if (rd1_dim0_cnt >= rd1_dim1_i - 13'd1) begin
                rd1_dim0_cnt <= 14'd0;
                rd1_dim1_cnt <= rd1_dim1_cnt + 13'd1;
            end else begin
                rd1_dim0_cnt <= rd1_dim0_cnt + 14'd1;
            end
        end
    end

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            rd1_req_addr_o <= 32'd0;
            rd1_req_vld_o  <= 1'b0;
        end else if (rd1_addr_gen_go && !rd1_req_vld_o) begin
            rd1_req_addr_o <= rd1_cur_addr;
            rd1_req_vld_o  <= 1'b1;
        end else if (rd1_req_rdy_i) begin
            rd1_req_vld_o  <= 1'b0;
        end
    end

    //══════════════════════════════════════════════════════════════
    // INPUT_ALIGN (RD0 only)
    //══════════════════════════════════════════════════════════════
    // For FP input: find max exponent among 32 elements, align mantissas
    // For INT input: pass through unchanged
    reg [P_IO_DATA_WD-1:0] align_data;
    reg [7:0]               align_exp;
    reg                     align_valid;

    // Simplified INPUT_ALIGN: for FP8/FP16, extract per-element exp, find max, shift mantissas
    // For INT: bypass
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            align_data  <= 'd0;
            align_exp   <= 8'd0;
            align_valid <= 1'b0;
        end else if (rd0_rsp_vld_i) begin
            rd0_rsp_rdy_o <= 1'b1;
            if (is_fp) begin
                // FP alignment: find max exp among elements
                // Simplified: for FP16 32 elements per 512-bit
                // Each FP16: [15]=sign [14:10]=exp [9:0]=man
                align_exp  <= 8'd0;  // placeholder
                align_data <= rd0_rsp_data_i;
            end else begin
                // INT: pass through
                align_exp  <= 8'd0;
                align_data <= rd0_rsp_data_i;
            end
            align_valid <= 1'b1;
       end else begin
            rd0_rsp_rdy_o <= 1'b0;
            align_valid   <= 1'b0;
       end
    end

    //══════════════════════════════════════════════════════════════
    // FRR_DISPATCHER (Fair Round-Robin dispatch to CIMEs)
    //══════════════════════════════════════════════════════════════
    reg [1:0] dispatch_ptr;  // 0-3 → CIME[0-3]
    reg [1:0] dispatch_mode; // 1/2/4 per slave

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n)
            dispatch_ptr <= 2'd0;
        else if (align_valid && cim_ready_i[dispatch_ptr])
            dispatch_ptr <= dispatch_ptr + 2'd1;
    end

    // Dispatch mode: from shape analysis in mpu_ctrl
    // active_cime_i = 1 → DISP_MODE_1X (1 CIME full)
    // active_cime_i = 2 → DISP_MODE_2X (2 CIME)
    // active_cime_i = 4 → DISP_MODE_4X
    always @(*) begin
        case (active_cime_i)
            4'd1: dispatch_mode = `DISP_MODE_1X;
            4'd2: dispatch_mode = `DISP_MODE_2X;
            4'd3, 4'd4: dispatch_mode = `DISP_MODE_4X;
            default: dispatch_mode = `DISP_MODE_1X;
        endcase
    end

    // CIME mask from ctrl
    wire [3:0] active_mask = cime_mask_i;

    // Route data only to active CIMEs
    wire [1:0] dispatch_target = dispatch_ptr & (active_cime_i - 4'd1);

    //══════════════════════════════════════════════════════════════
    // SHAPING_REG → CIMC output
    //══════════════════════════════════════════════════════════════
    integer ci;
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            for (ci = 0; ci < CIME_NUM; ci = ci + 1) begin
                cim_data_o[ci]  <= 'd0;
                cim_exp_o[ci]   <= 8'd0;
                cim_valid_o[ci] <= 1'b0;
            end
        end else if (align_valid) begin
            // Route aligned data to target CIME
            for (ci = 0; ci < CIME_NUM; ci = ci + 1) begin
                if (ci == dispatch_ptr) begin
                    cim_data_o[ci]  <= align_data;
                    cim_exp_o[ci]   <= align_exp;
                    cim_valid_o[ci] <= 1'b1;
                end else begin
                    cim_valid_o[ci] <= 1'b0;
                end
            end
        end else begin
            for (ci = 0; ci < CIME_NUM; ci = ci + 1)
                cim_valid_o[ci] <= 1'b0;
        end
    end

    //── Perf counters ────────────────────────────────────────────
    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            perf_rd0_cnt_o <= 32'd0;
            perf_rd1_cnt_o <= 32'd0;
        end else begin
            if (rd0_rsp_vld_i && rd0_rsp_rdy_o)
                perf_rd0_cnt_o <= perf_rd0_cnt_o + 32'd2;  // 512-bit = 2×256
            if (rd1_rsp_vld_i && rd1_rsp_rdy_o)
                perf_rd1_cnt_o <= perf_rd1_cnt_o + 32'd1;  // per read
        end
    end

endmodule
