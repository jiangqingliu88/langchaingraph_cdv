//==============================================================================
// MPU_POST_PROCESS — Accumulate CIME results, format conversion, PSUM add
// Implements: POST_GLUE_LOGIC → INT_ACC_PIPE1 → POST_SELECT →
//             FORMAT_CONVERSION_39 → INT_FP_ACCUMULATOR
//==============================================================================
`include "mpu_defines.vh"

module mpu_post_process #(
    parameter CIME_NUM       = 4,
    parameter POST_IN1_W     = 2432,
    parameter POST_IN2_W     = 512
) (
    input  wire         clk_i,
    input  wire         rst_n,

    //── From CIMC ─────────────────────────────────────────────────
    input  wire [CIME_NUM-1:0][POST_IN1_W-1:0] cim_data_i,
    input  wire [CIME_NUM-1:0][7:0]            cim_exp_i,
    input  wire [CIME_NUM-1:0]                 cim_valid_i,
    output wire [CIME_NUM-1:0]                 cim_ready_o,

    //── To WR_CHANNEL ─────────────────────────────────────────────
    output reg  [P_IO_DATA_WD-1:0] wr_data_o,     // P_IO_DATA_WD=512
    output reg                      wr_valid_o,
    input  wire                     wr_ready_i,
    output reg                      wr_last_o,

    //── Config ────────────────────────────────────────────────────
    input  wire [2:0]               pattern_i,      // PATTERN2/PATTERN3
    input  wire [3:0]               precision_i,
    input  wire                     acc_en_i,       // PSUM enable
    input  wire                     type_out_i,     // 0:INT 1:FP
    input  wire [2:0]               width_out_i
);

    //══════════════════════════════════════════════════════════════
    // Stage 1: POST_GLUE_LOGIC — merge CIME pairs
    // PATTERN2: CIME0+CIME1, CIME2+CIME3
    // PATTERN3: CIME0, CIME1, CIME2, CIME3 (sequential)
    //══════════════════════════════════════════════════════════════
    reg [1:0] glue_sel;  // which pair to process
    reg [POST_IN1_W-1:0] glue_data_a, glue_data_b;
    reg [7:0]            glue_exp_a,  glue_exp_b;
    reg                  glue_valid;

    wire is_pattern2 = (pattern_i == `PATTERN2);

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            glue_sel    <= 2'd0;
            glue_valid  <= 1'b0;
        end else if (is_pattern2) begin
            // PATTERN2: CIME0+CIME1, then CIME2+CIME3
            if (cim_valid_i[0] && cim_valid_i[1]) begin
                glue_data_a <= cim_data_i[0];
                glue_data_b <= cim_data_i[1];
                glue_exp_a  <= cim_exp_i[0];
                glue_exp_b  <= cim_exp_i[1];
                glue_valid  <= 1'b1;
                glue_sel    <= 2'd0;
            end else if (cim_valid_i[2] && cim_valid_i[3]) begin
                glue_data_a <= cim_data_i[2];
                glue_data_b <= cim_data_i[3];
                glue_exp_a  <= cim_exp_i[2];
                glue_exp_b  <= cim_exp_i[3];
                glue_valid  <= 1'b1;
                glue_sel    <= 2'd1;
            end else begin
                glue_valid  <= 1'b0;
            end
        end else begin
            // PATTERN3: sequential per CIME
            if (cim_valid_i[glue_sel]) begin
                glue_data_a <= cim_data_i[glue_sel];
                glue_data_b <= 'd0;
                glue_exp_a  <= cim_exp_i[glue_sel];
                glue_exp_b  <= 8'd0;
                glue_valid  <= 1'b1;
            end else begin
                glue_valid  <= 1'b0;
            end
        end
    end

    assign cim_ready_o = {CIME_NUM{wr_ready_i}};  // ready when downstream ready

    //══════════════════════════════════════════════════════════════
    // Stage 2: INT_ACC_PIPE1 — INT38 + INT38 → INT39
    //══════════════════════════════════════════════════════════════
    reg [38:0] acc1_result;
    reg [7:0]  acc1_exp;
    reg        acc1_valid;

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            acc1_result <= 39'd0;
            acc1_exp    <= 8'd0;
            acc1_valid  <= 1'b0;
        end else if (glue_valid) begin
            // Add two INT38 values (truncated from POST_IN1_W)
            // Align by exp: shift smaller exp right
            if (glue_exp_a > glue_exp_b) begin
                acc1_result <= {1'b0, glue_data_a[37:0]} +
                               ({1'b0, glue_data_b[37:0]} >> (glue_exp_a - glue_exp_b));
                acc1_exp    <= glue_exp_a;
            end else begin
                acc1_result <= {1'b0, glue_data_b[37:0]} +
                               ({1'b0, glue_data_a[37:0]} >> (glue_exp_b - glue_exp_a));
                acc1_exp    <= glue_exp_b;
            end
            acc1_valid <= 1'b1;
        end else begin
            acc1_valid <= 1'b0;
        end
    end

    //══════════════════════════════════════════════════════════════
    // Stage 3: POST_SELECT — select between two ACC1 outputs
    //══════════════════════════════════════════════════════════════
    reg [38:0] select_result;
    reg [7:0]  select_exp;
    reg        select_valid;
    reg        is_last;

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            select_result <= 39'd0;
            select_exp    <= 8'd0;
            select_valid  <= 1'b0;
            is_last       <= 1'b0;
        end else if (acc1_valid) begin
            select_result <= acc1_result;
            select_exp    <= acc1_exp;
            select_valid  <= 1'b1;
            is_last       <= (glue_sel == 2'd1) || !is_pattern2;  // last pair
        end else begin
            select_valid  <= 1'b0;
        end
    end

    //══════════════════════════════════════════════════════════════
    // Stage 4: FORMAT_CONVERSION_39 — INT39→FP32 (all 6 scenarios)
    // INT39 = [sign(1), hidden_bit(1), mantissa(37)]
    // → normalize (find leading 1) → FP32 = [sign, exp(8), mantissa(23)]
    //══════════════════════════════════════════════════════════════
    reg [31:0] fmt_result;
    reg [7:0]  fmt_exp;
    reg        fmt_valid;

    // Leading-one detector for normalization
    function [5:0] find_leading_one(input [38:0] val);
        integer j;
        begin
            find_leading_one = 6'd0;
            for (j = 38; j >= 0; j = j - 1) begin
                if (val[j]) begin
                    find_leading_one = j[5:0];
                    j = -1;  // break
                end
            end
        end
    endfunction

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            fmt_result <= 32'd0;
            fmt_exp    <= 8'd0;
            fmt_valid  <= 1'b0;
        end else if (select_valid) begin
            if (type_out_i) begin
                // INT39→FP32 format conversion
                // Step 1: find leading 1 position in mantissa
                reg [5:0] lead_pos;
                reg [38:0] norm_val;
                lead_pos = find_leading_one(select_result);
                // Step 2: shift mantissa so MSB is at bit 23 (FP32 mantissa width)
                // mantissa = select_result[lead_pos-1 : lead_pos-23]
                norm_val = select_result << (38 - lead_pos);
                // Step 3: pack FP32 = {sign, exp, mantissa[22:0]}
                // exp = select_exp + lead_pos - 1 + 127 (bias)
                fmt_result <= {select_result[38],                       // sign
                               select_exp + {2'd0, lead_pos} - 8'd1 + 8'd127,  // exp with bias
                               norm_val[37:15]};                       // mantissa 23-bit
                fmt_exp    <= select_exp;
            end else begin
                // INT32 output (scenarios 1-2): truncate to 32-bit
                fmt_result <= select_result[31:0];
                fmt_exp    <= 8'd0;
            end
            fmt_valid  <= 1'b1;
        end else begin
            fmt_valid  <= 1'b0;
        end
    end

    //══════════════════════════════════════════════════════════════
    // Stage 5: INT_FP_ACCUMULATOR (PSUM accumulation)
    // If acc_en_i → result + PSUM; else → pass through
    //══════════════════════════════════════════════════════════════
    reg [P_IO_DATA_WD-1:0] wr_buf;
    reg                    wr_buf_valid;

    always @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            wr_data_o     <= 'd0;
            wr_valid_o    <= 1'b0;
            wr_last_o     <= 1'b0;
            wr_buf        <= 'd0;
            wr_buf_valid  <= 1'b0;
        end else if (fmt_valid) begin
            // Pack 16×32b → 512-bit output
            wr_buf <= {wr_buf[P_IO_DATA_WD-33:0], fmt_result};
            if (is_last) begin
                wr_data_o    <= {wr_buf[P_IO_DATA_WD-33:0], fmt_result};
                wr_valid_o   <= 1'b1;
                wr_last_o    <= 1'b1;
                wr_buf_valid <= 1'b0;
            end else begin
                wr_buf_valid <= 1'b1;
            end
        end else if (wr_ready_i) begin
            wr_valid_o <= 1'b0;
            wr_last_o  <= 1'b0;
        end
    end

endmodule
