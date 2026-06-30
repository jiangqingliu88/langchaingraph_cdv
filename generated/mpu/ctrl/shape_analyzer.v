//==============================================================================
// shape_analyzer — PATTERN-dependent activation shape computation
//
// PATTERN2 (2×2 block):  4 CIME in 2-row × 2-col grid
//   Row0: CIME0(left) + CIME1(right)    Row1: CIME2(left) + CIME3(right)
//   Total width per row: 2 × 512bit = 1024bit (128 CHANNEL)
//   Per-CIME width: 512bit (64 CHANNEL × 8bit)
//   Weight shape: ~square (128CH × 512bit)
//
// PATTERN3 (1×4 strip):  4 CIME in single row
//   CIME0 | CIME1 | CIME2 | CIME3  (sequential, left→right)
//   Total width: 1024bit (or 4 × 256bit) = 64 CHANNEL
//   Per-CIME width: 256bit (when 8bit weight) or 512bit (when 16bit)
//   Weight shape: wide-flat (64CH × 1024bit)
//
// Activation shape determined by DIM0 (32B units):
//   DIM0_IN  = input activation width in 32B units
//   DIM0_OUT = output width in 32B units
//
// Shape variations per PATTERN:
//   PATTERN2 max: 64 × 512bit per CIME, 32 × 256bit, 32 × 512bit
//   PATTERN3 max: 32 × 1024bit total
//==============================================================================
module shape_analyzer (
    input  wire [2:0]   pattern_i,       // PATTERN2=010 / PATTERN3=100
    input  wire [13:0]  dim0_in_i,       // input DIM0 (32B units)
    input  wire [13:0]  dim0_out_i,      // output DIM0 (32B units)
    input  wire [2:0]   width_in_i,      // input precision width
    input  wire [2:0]   width_wt_i,      // weight precision width
    input  wire [2:0]   width_out_i,     // output precision width

    //── Shape outputs ────────────────────────────────────────────
    output reg  [1:0]   grid_rows_o,     // PATTERN2=2, PATTERN3=1
    output reg  [1:0]   grid_cols_o,     // PATTERN2=2, PATTERN3=4
    output reg  [3:0]   active_cime_o,   // total active CIMEs
    output reg  [9:0]   cime_in_width_o, // bits per CIME for input
    output reg  [9:0]   cime_wt_width_o, // bits per CIME for weight
    output reg  [5:0]   rows_per_cime_o, // weight rows used per CIME
    output reg  [13:0]  dim0_cols_o,     // number of "columns" of data
    output reg  [5:0]   elems_per_row_o  // elements per CIME row
);

    //── PATTERN decode ───────────────────────────────────────────
    wire is_pt2 = (pattern_i == `PATTERN2);
    wire is_pt3 = (pattern_i == `PATTERN3);

    //── Grid topology ────────────────────────────────────────────
    // PATTERN2: 2 rows × 2 cols  (CIME0,1 top; CIME2,3 bottom)
    // PATTERN3: 1 row  × 4 cols  (CIME0,1,2,3 in single row)
    always @(*) begin
        if (is_pt2) begin
            grid_rows_o   = 2'd2;
            grid_cols_o   = 2'd2;
            active_cime_o = 4'd4;      // all 4 CIMEs active
        end else begin  // PATTERN3 (and default)
            grid_rows_o   = 2'd1;
            grid_cols_o   = 2'd3;      // 0-3 = 4 columns
            active_cime_o = 4'd4;
        end
    end

    //── Per-CIME width based on PATTERN ──────────────────────────
    // PATTERN2: each CIME gets 512-bit input channel
    // PATTERN3: each CIME gets 256-bit (weight 8b) or 512-bit (weight 16b)
    always @(*) begin
        if (is_pt2) begin
            cime_in_width_o = 10'd512;   // full 512b per CIME
            cime_wt_width_o = 10'd512;
        end else begin
            // PATTERN3: width depends on weight precision
            case (width_wt_i)
                3'b010: cime_wt_width_o = 10'd512;  // 4b→64elem→512b
                3'b011: cime_wt_width_o = 10'd256;  // 8b→32elem→256b
                3'b100: cime_wt_width_o = 10'd256;  // 16b→16elem→256b
                default: cime_wt_width_o = 10'd256;
            endcase
            cime_in_width_o = 10'd512;  // input always 512b
        end
    end

    //── Weight rows per CIME ─────────────────────────────────────
    // PATTERN2: CIMM has 32 rows, all used → rows_per_cime = 32
    // PATTERN3: CIMM rows split across wider array
    always @(*) begin
        if (is_pt2)
            rows_per_cime_o = 6'd32;    // full 32 rows
        else
            rows_per_cime_o = 6'd32;    // also 32 rows, but wider
    end

    //── DIM0 columns: how many data columns to process ───────────
    // DIM0_IN in 32B units = how many 256-bit chunks of activation
    // Each "column" = per-CIME input width
    //   PATTERN2: 1 column = 512b = 2×32B → dim0_cols = dim0_in / 2
    //   PATTERN3: 1 column = 512b = 2×32B → dim0_cols = dim0_in / 2
    always @(*) begin
        // DIM0 is in 32B (256-bit) units
        // Each CIME processes 512-bit (64B) per column = 2×32B units
        if (is_pt2) begin
            // 2 CIMEs per row × 512bit = 1024bit per row-column
            dim0_cols_o = dim0_in_i >> 1;    // /2 because 512b=2×32B
        end else begin
            // 1 CIME per column × 512bit input
            dim0_cols_o = dim0_in_i >> 1;
        end
    end

    //── Elements per CIME row ────────────────────────────────────
    // = CIME input width / element width
    always @(*) begin
        case (width_in_i)
            3'b010: elems_per_row_o = 6'd128;  // 512/4 = 128
            3'b011: elems_per_row_o = 6'd64;   // 512/8 = 64
            3'b100: elems_per_row_o = 6'd32;   // 512/16 = 32
            3'b101: elems_per_row_o = 6'd16;   // 512/32 = 16
            default: elems_per_row_o = 6'd64;
        endcase
    end

endmodule
